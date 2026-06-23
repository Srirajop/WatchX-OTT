# file_reader.py — Reads ANY subtitle/script file format
# Handles: DOC, DOCX, PDF, SRT, VTT, XML, TTML, RTF, TXT, XLSX, XLS, CSV
# Preserves structure for AI to understand context

import io
import re
import chardet


def read_file(file_bytes: bytes, filename: str) -> dict:
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else "txt"

    # ── Magic-byte sniffing: detect misnamed files ──────────────────────────
    # A file saved as .pdf but actually a DOCX/ZIP will start with PK (0x50 0x4B)
    # A file saved as .docx but actually PDF will start with %PDF
    if len(file_bytes) >= 4:
        magic = file_bytes[:4]
        if ext == "pdf" and magic[:2] == b'PK':
            # ZIP magic — try as DOCX first
            ext = "docx"
        elif ext in ("docx", "doc") and magic[:4] == b'%PDF':
            ext = "pdf"

    readers = {
        "docx": read_docx, "doc": read_legacy_doc,
        "pdf": read_pdf,
        "srt": read_srt,
        "vtt": read_vtt, "webvtt": read_vtt,
        "xml": read_xml, "ttml": read_xml, "dfxp": read_xml,
        "rtf": read_rtf,
        "xlsx": read_excel, "xls": read_excel,
        "csv": read_csv,
        "txt": read_plain,
        "json": read_json,
    }

    reader = readers.get(ext, read_plain)

    try:
        raw_text = reader(file_bytes)
    except Exception:
        raw_text = decode_bytes(file_bytes)

    # ── Garbled-output guard ─────────────────────────────────────────────────
    # If the extracted text has too many non-printable / non-ASCII chars,
    # or if it contains obvious DOCX zip markers, the PDF was probably
    # image-only or corrupted/misnamed. Try the other reader.
    if raw_text and ext == "pdf":
        sample = raw_text[:500].replace('\n', '').replace('\r', '')
        printable = sum(1 for c in sample if c.isprintable())
        # If it looks like binary garbage, or if it's literally a DOCX
        if (len(sample) > 0 and printable / len(sample) < 0.60) or "word/document.xml" in raw_text[:1000]:
            # Likely binary garbage or a disguised DOCX — try DOCX as fallback
            try:
                alt = read_docx(file_bytes)
                if alt and alt.strip():
                    raw_text = alt
                    ext = "docx"
            except Exception:
                pass

    if not raw_text or not raw_text.strip():
        raw_text = decode_bytes(file_bytes)

    structure = detect_structure(raw_text, ext)

    return {
        "raw_text": raw_text,
        "structure": structure,
        "filename": filename,
        "format": ext.upper()
    }



def detect_structure(text: str, ext: str) -> str:
    if ext == "srt" or re.search(r'\d+\n\d{2}:\d{2}:\d{2},\d{3}\s+-->', text):
        return "srt_format"
    if ext in ["vtt", "webvtt"] or text.startswith("WEBVTT"):
        return "vtt_format"
    if ext in ["xml", "ttml", "dfxp"] or "<tt " in text or "<body>" in text:
        return "xml_ttml"
    # CCSL / Spotting List detection — check for header with TimeIn/TimeOut/Titles columns
    # This fires both for standard CCSL PDFs and for spatial-parser output
    if re.search(r'(TimeIn|Time\s+In)\s*\|.*(TimeOut|Time\s+Out)\s*\|.*(Titles?|Dialogue)', text, re.IGNORECASE):
        return "ccsl_double_dialogue"
    if "COMBINED CONTINUITY" in text or "CCSL" in text.upper() or "SPOTTING LIST" in text.upper():
        return "ccsl_double_dialogue"
    # Table with HH:MM:SS:FF timecodes — includes spatial parser output
    if re.search(r'\d{2}:\d{2}:\d{2}[:;]\d{2}', text) and '|' in text:
        return "table_with_timecodes"
    if "=== TABLE" in text and re.search(r'\d{2}:\d{2}:\d{2}', text):
        return "table_with_timecodes"
    if re.search(r'\d{2}:\d{2}:\d{2}[:;]\d{2}', text) and re.search(r'(INT\.|EXT\.|OS\)|VO\))', text):
        return "paragraph_without_table"
    if re.search(r'(INT\.|EXT\.|TEASER|ACT ONE|SCENE)', text, re.IGNORECASE):
        return "paragraph_with_speaker"
    if ext in ["xlsx", "xls", "csv"] or "=== SHEET" in text:
        return "excel_spotting_list"
    lines = [l for l in text.splitlines() if l.strip()]
    if len(lines) > 5 and all(len(l) < 120 for l in lines[:20]):
        return "plain_script"
    return "unknown"



def decode_bytes(b: bytes) -> str:
    detected = chardet.detect(b)
    enc = detected.get("encoding") or "utf-8"
    try:
        return b.decode(enc, errors="ignore")
    except:
        return b.decode("utf-8", errors="ignore")


def read_docx(file_bytes: bytes) -> str:
    sections = []
    try:
        from docx import Document
        doc = Document(io.BytesIO(file_bytes))
        paras = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        if paras:
            sections.append("=== PARAGRAPHS ===")
            sections.extend(paras)

        for i, table in enumerate(doc.tables):
            sections.append(f"\n=== TABLE {i+1} ({len(table.rows)} rows x {len(table.columns)} cols) ===")
            for row in table.rows:
                cells = []
                seen = set()
                for cell in row.cells:
                    t = cell.text.strip()
                    if t and t not in seen:
                        cells.append(t)
                        seen.add(t)
                if cells:
                    sections.append(" | ".join(cells))
        return "\n".join(sections)
    except Exception as e:
        # Fallback for poorly formed DOCX files (like missing app.xml)
        import zipfile
        import xml.etree.ElementTree as ET
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
                xml_content = z.read('word/document.xml')
                root = ET.fromstring(xml_content)
                lines = []
                # Find all body elements: paragraphs and tables
                body = None
                for elem in root.iter():
                    if elem.tag.endswith('}body'):
                        body = elem
                        break
                if not body:
                    body = root

                for child in body:
                    if child.tag.endswith('}p'):
                        p_text = []
                        for t_elem in child.iter():
                            if t_elem.tag.endswith('}t') and t_elem.text:
                                p_text.append(t_elem.text)
                        joined = "".join(p_text).strip()
                        if joined:
                            lines.append(joined)
                    elif child.tag.endswith('}tbl'):
                        lines.append("=== TABLE ===")
                        for row in child.iter():
                            if row.tag.endswith('}tr'):
                                cells = []
                                for tc in row.iter():
                                    if tc.tag.endswith('}tc'):
                                        tc_text = []
                                        for t_elem in tc.iter():
                                            if t_elem.tag.endswith('}t') and t_elem.text:
                                                tc_text.append(t_elem.text)
                                        cells.append("".join(tc_text).strip())
                                if any(cells):
                                    lines.append(" | ".join(cells))
                return "\n".join(lines)
        except:
            raise e


def read_legacy_doc(file_bytes: bytes) -> str:
    import tempfile
    import os
    try:
        from spire.doc import Document
    except ImportError:
        return decode_bytes(file_bytes)
        
    fd, path = tempfile.mkstemp(suffix=".doc")
    with os.fdopen(fd, 'wb') as f:
        f.write(file_bytes)
    
    try:
        from spire.doc import Document, DocumentObjectType
        document = Document()
        document.LoadFromFile(path)
        
        lines = []
        for i in range(document.Sections.Count):
            section = document.Sections.get_Item(i)
            for j in range(section.Body.ChildObjects.Count):
                obj = section.Body.ChildObjects.get_Item(j)
                if obj.DocumentObjectType == DocumentObjectType.Paragraph:
                    text = obj.Text.strip()
                    if text and "Evaluation Warning:" not in text:
                        lines.append(text)
                elif obj.DocumentObjectType == DocumentObjectType.Table:
                    table = obj
                    for r in range(table.Rows.Count):
                        row = table.Rows.get_Item(r)
                        cells = []
                        for c in range(row.Cells.Count):
                            cell = row.Cells.get_Item(c)
                            cell_text = []
                            for k in range(cell.Paragraphs.Count):
                                pt = cell.Paragraphs.get_Item(k).Text.strip()
                                if pt: cell_text.append(pt)
                            cells.append(" ".join(cell_text).strip())
                        if any(cells):
                            lines.append(" | ".join(cells))
                            
        result = "\n".join(lines).strip()
        import sys
        print("DEBUG read_legacy_doc: SUCCESS, len=", len(result), "tables_found=", len([l for l in lines if '|' in l]), file=sys.stderr)
        return result
    except Exception as e:
        import sys
        print(f"Spire.Doc error: {e}", file=sys.stderr)
        return decode_bytes(file_bytes)
    finally:
        try:
            os.remove(path)
        except:
            pass


def read_pdf(file_bytes: bytes) -> str:
    sections = []
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for i, page in enumerate(pdf.pages):
                sections.append(f"=== PAGE {i+1} ===")
                # Extract tables with style preservation
                tables = page.extract_tables()
                valid_tables = [t for t in tables if any(cell and str(cell).strip() for row in t for cell in row)]
                
                if valid_tables:
                    for t_idx, table in enumerate(valid_tables):
                        sections.append(f"=== TABLE {t_idx+1} ===")
                        for row in table:
                            cells = [re.sub(r'\s+', ' ', str(c)).strip() for c in row if c is not None and str(c).strip()]
                            if cells: sections.append(" | ".join(cells))
                else:
                    # Fallback to spatial parsing with font awareness
                    words = page.extract_words(keep_blank_chars=True, extra_attrs=["fontname", "size"])
                    lines_dict = {}
                    for w in words:
                        text = w['text']
                        if 'Bold' in w.get('fontname', ''): text = f"**{text}**"
                        elif 'Italic' in w.get('fontname', ''): text = f"*{text}*"
                        y = round(w['top'])
                        if y not in lines_dict: lines_dict[y] = []
                        lines_dict[y].append((w['x0'], text))
                    for y in sorted(lines_dict.keys()):
                        row_items = sorted(lines_dict[y], key=lambda x: x[0])
                        line = " ".join(item[1] for item in row_items).strip()
                        if line:
                            sections.append(line)

        # ── CCSL / Spotting List spatial repair ───────────────────────────
        # Detect if pdfplumber extracted ONLY header rows (no actual data).
        # This happens with complex CCSL PDFs where table cells render but are
        # empty in extract_tables() output.
        full_text = "\n".join(sections)
        data_lines = [
            l for l in full_text.splitlines()
            if l.strip() and not l.startswith("===") and "|" in l
            and not re.match(
                r'^\s*(Sh#|Sh\s*Time\s*In|ShTimeIn|Scene\s*Description|Title\s*\||'
                r'Time\s*In\s*\||Time\s*Out\s*\||Dur\s*\||Titles?\s*\|?)\s*',
                l.strip(), re.IGNORECASE
            )
        ]
        if not data_lines:
            # All table data is missing — parse word-by-word using bounding boxes
            spatial = _read_pdf_spatial(file_bytes)
            if spatial and spatial.strip():
                return spatial

        return full_text

    except Exception as e:
        import sys
        print(f"pdfplumber error: {e}", file=sys.stderr)
        try:
            import PyPDF2
            reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
            pages = []
            for i, p in enumerate(reader.pages):
                t = p.extract_text() or ""
                if t.strip():
                    pages.append(f"=== PAGE {i+1} ===\n{t}")
            return "\n".join(pages)
        except Exception as e2:
            import sys
            print(f"PyPDF2 fallback error: {e2}", file=sys.stderr)
            return ""


def _read_pdf_spatial(file_bytes: bytes) -> str:
    """
    Spatial word-by-word PDF parser for CCSL spotting list PDFs.

    When pdfplumber's table extractor yields only header rows and no data,
    this function reconstructs the table by:
    1. Extracting all words with bounding boxes and font info.
    2. Grouping words into visual rows by y-coordinate (±3px).
    3. Detecting the header row to learn column x-boundaries.
    4. Assigning each subsequent word to a column by x-position.
    5. Returning pipe-separated rows.

    Bold/italic font names are preserved as **word** / *word* markers so the
    downstream cleaner can apply <i>/<b> tags correctly.
    The CCSL columns are:
      Sh# | ShTimeIn | SceneDescription | Title | TimeIn | TimeOut | Dur | Titles
    We care most about TimeIn, TimeOut, and Titles (the subtitle text).
    """
    import sys
    try:
        import pdfplumber
    except ImportError:
        return ""

    all_lines = []
    header_printed = False

    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            # Detect global column boundaries from first page that has a header
            global_col_bounds: list[float] = []

            for page_num, page in enumerate(pdf.pages):
                try:
                    words = page.extract_words(
                        keep_blank_chars=False,
                        extra_attrs=["fontname", "size"],
                        x_tolerance=2,
                        y_tolerance=3,
                    )
                except Exception:
                    words = page.extract_words(keep_blank_chars=False)

                if not words:
                    continue

                # Group words into visual rows (snap y to 3px grid)
                rows: dict[int, list] = {}
                for w in words:
                    y_key = round(w["top"] / 3) * 3
                    if y_key not in rows:
                        rows[y_key] = []
                    text = w["text"]
                    fname = w.get("fontname", "")
                    if re.search(r'Bold|Heavy|Black', fname, re.IGNORECASE):
                        text = f"**{text}**"
                    elif re.search(r'Italic|Oblique', fname, re.IGNORECASE):
                        text = f"*{text}*"
                    rows[y_key].append((w["x0"], w["x1"], text))

                sorted_y = sorted(rows.keys())

                # Find header row on this page
                col_bounds: list[float] = list(global_col_bounds)
                header_y = None

                for y in sorted_y:
                    row_words = sorted(rows[y], key=lambda x: x[0])
                    row_text = " ".join(w[2] for w in row_words)
                    if re.search(r'(Sh#|ShTimeIn|SceneDescription|Time\s*In|Time\s*Out|Titles)', row_text, re.IGNORECASE):
                        col_bounds = [w[0] for w in row_words]
                        if not global_col_bounds:
                            global_col_bounds = col_bounds
                        header_y = y
                        if not header_printed:
                            # Output a clean header line for downstream parsers
                            header_line = " | ".join(w[2] for w in row_words)
                            all_lines.append(header_line)
                            header_printed = True
                        break

                def assign_col(x0: float, bounds: list[float]) -> int:
                    for idx in range(len(bounds) - 1, -1, -1):
                        if x0 >= bounds[idx] - 8:
                            return idx
                    return 0

                for y in sorted_y:
                    if header_y is not None and y <= header_y:
                        continue
                    row_words = sorted(rows[y], key=lambda x: x[0])
                    if not row_words:
                        continue

                    if col_bounds and len(col_bounds) >= 4:
                        col_groups: dict[int, list[str]] = {}
                        for (x0, x1, text) in row_words:
                            col = assign_col(x0, col_bounds)
                            col_groups.setdefault(col, []).append(text)
                        num_cols = len(col_bounds)
                        cells = [" ".join(col_groups.get(c, [])).strip() for c in range(num_cols)]
                        if any(c for c in cells):
                            all_lines.append(" | ".join(cells))
                    else:
                        line = " ".join(w[2] for w in row_words).strip()
                        if line:
                            all_lines.append(line)

    except Exception as e:
        import sys
        print(f"[_read_pdf_spatial] error: {e}", file=sys.stderr)

    return "\n".join(all_lines)


def read_srt(file_bytes: bytes) -> str:
    return decode_bytes(file_bytes)


def read_vtt(file_bytes: bytes) -> str:
    return decode_bytes(file_bytes)


def read_xml(file_bytes: bytes) -> str:
    import xml.etree.ElementTree as ET
    raw = decode_bytes(file_bytes)
    lines = []
    try:
        root = ET.fromstring(raw)
        def strip_ns(tag):
            return tag.split("}")[-1] if "}" in tag else tag
        for elem in root.iter():
            tag = strip_ns(elem.tag)
            text = (elem.text or "").strip()
            if tag in ["p", "span"] and text:
                begin = elem.attrib.get("begin", "")
                end = elem.attrib.get("end", "")
                lines.append(f"{begin} --> {end} | {text}" if begin else text)
    except:
        lines = [t.strip() for t in re.findall(r">([^<]+)<", raw) if t.strip()]
    return "\n".join(lines)


def read_rtf(file_bytes: bytes) -> str:
    try:
        from striprtf.striprtf import rtf_to_text
        return rtf_to_text(decode_bytes(file_bytes))
    except:
        text = decode_bytes(file_bytes)
        text = re.sub(r'\\[a-zA-Z]+\-?\d*\s?', ' ', text)
        text = re.sub(r'[{}\\]', '', text)
        return re.sub(r'\s+', ' ', text).strip()


def read_excel(file_bytes: bytes) -> str:
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
        sections = []
        for sheet in wb.worksheets:
            sections.append(f"=== SHEET: {sheet.title} ===")
            for row in sheet.iter_rows(values_only=True):
                cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
                if cells:
                    sections.append(" | ".join(cells))
        return "\n".join(sections)
    except:
        import xlrd
        wb = xlrd.open_workbook(file_contents=file_bytes)
        sections = []
        for sheet in wb.sheets():
            sections.append(f"=== SHEET: {sheet.name} ===")
            for r in range(sheet.nrows):
                cells = [str(sheet.cell_value(r, c)).strip()
                         for c in range(sheet.ncols)
                         if str(sheet.cell_value(r, c)).strip()]
                if cells:
                    sections.append(" | ".join(cells))
        return "\n".join(sections)


def read_csv(file_bytes: bytes) -> str:
    import csv
    text = decode_bytes(file_bytes)
    reader = csv.reader(io.StringIO(text))
    lines = [" | ".join(c.strip() for c in row if c.strip()) for row in reader]
    return "\n".join(l for l in lines if l)


def read_plain(file_bytes: bytes) -> str:
    return decode_bytes(file_bytes)


def read_json(file_bytes: bytes) -> str:
    import json
    try:
        data = json.loads(decode_bytes(file_bytes))
        return json.dumps(data, indent=2, ensure_ascii=False)
    except:
        return decode_bytes(file_bytes)
