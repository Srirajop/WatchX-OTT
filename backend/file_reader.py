# file_reader.py — Reads ANY subtitle/script file format
# Handles: DOC, DOCX, PDF, SRT, VTT, XML, TTML, RTF, TXT, XLSX, XLS, CSV, PMW
# Preserves structure for AI to understand context

import io
import re
import chardet


class UnsupportedPMWError(ValueError):
    pass
_PDF_METADATA_LINE = re.compile(r'^\s*(?:===|Original\s+title:|Translated\s+title:|Language:|File:|Printed\s+on\s+.+\bPage\s+\d+\s*$)', re.IGNORECASE)
_PDF_TIMECODE = re.compile(r'\b\d{2}:\d{2}:\d{2}[.:;]\d{2}\b')

def _pdf_text_needs_outline_ocr(text: str) -> bool:
    timecode_lines = word_count = 0
    for line in text.splitlines():
        line = line.strip()
        if not line or _PDF_METADATA_LINE.match(line):
            continue
        if _PDF_TIMECODE.search(line):
            timecode_lines += 1
            line = _PDF_TIMECODE.sub(' ', line)
            line = re.sub(r'\b\d+(?:[.:]\d+)*\b', ' ', line)
        word_count += len(re.findall(r"[A-Za-z][A-Za-z'-]{1,}", line))
    return timecode_lines >= 20 and word_count < max(20, timecode_lines // 5)


def _merge_pdf_timecodes_with_ocr(file_bytes: bytes, raw_text: str) -> str:
    from ocr_reader import render_pdf_pages_as_images, ocr_image_bytes
    import re
    
    pages_text = re.split(r'===\s*PAGE\s*\d+\s*===', raw_text)
    if pages_text and not pages_text[0].strip():
        pages_text.pop(0)
        
    images = render_pdf_pages_as_images(file_bytes)
    
    merged = []
    for i, img in enumerate(images):
        page_num = i + 1
        merged.append(f"=== PAGE {page_num} ===")
        
        if i < len(pages_text):
            merged.append("--- ACCURATE TIMECODES ---")
            merged.append(pages_text[i].strip())
            
        merged.append("--- OCR SUBTITLES (Match with timecodes above) ---")
        try:
            ocr_result = ocr_image_bytes(img)
            merged.append(ocr_result.strip())
        except Exception as e:
            merged.append(f"[OCR Failed: {e} - Ensure Tesseract OCR is installed]")
        merged.append("")
        
    return "\n".join(merged)


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
        "pmw": read_pmw,
    }

    reader = readers.get(ext, read_plain)

    try:
        raw_text = reader(file_bytes)
    except UnsupportedPMWError:
        raise
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

    # OCR fallback for PDFs — this runs after every other PDF extraction
    # strategy above (pdfplumber tables, spatial word-position parsing,
    # PyPDF2 fallback) has already had its chance. PDF has several distinct
    # return paths inside read_pdf() itself, so rather than touch each one,
    # this single check after the dispatcher covers all of them at once —
    # same end result, less risk of missing a branch.
    if ext == "pdf":
        try:
            from ocr_reader import ocr_fallback_for_pdf
            outline_text_missing = _pdf_text_needs_outline_ocr(raw_text)
            if outline_text_missing:
                raw_text = _merge_pdf_timecodes_with_ocr(file_bytes, raw_text)
            else:
                ocr_text = ocr_fallback_for_pdf(file_bytes, len(raw_text.strip()), force_page_render=False)
                if ocr_text:
                    raw_text = raw_text + "\n\n=== OCR EXTRACTED CONTENT ===\n" + ocr_text
        except Exception as e:
            print(f"[file_reader] OCR fallback skipped for PDF: {e}")

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
    # Table with timecodes — includes spatial parser output. Matches BOTH
    # frame-accurate HH:MM:SS:FF (e.g. CCSL spotting lists) AND second-only
    # HH:MM:SS (e.g. documentary-style "TIME CODE | VISUALS | AUDIO" tables
    # like the CAR SOS/Food Factory format, which has no frame component at
    # all) — a new client's table using either timecode precision should be
    # recognized without adding a new regex branch for it.
    # IMPORTANT: the timecode and the pipe must appear on the SAME LINE —
    # checking them independently anywhere in the whole document produces
    # false positives (e.g. a paragraph mentioning a clock time, with an
    # unrelated pipe character somewhere else in the file).
    if any(
        '|' in line and re.search(r'\d{2}:\d{2}:\d{2}([:;]\d{2})?', line)
        for line in text.splitlines()
    ):
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


def _useful_pmw_text(text: str) -> bool:
    if not text:
        return False
    words = re.findall(r"[^\W\d_]{2,}", text, re.UNICODE)
    timecodes = re.findall(r"\b\d{1,2}[:.]\d{2}[:.]\d{2}(?:[,.:;]\d{1,3})?\b", text)
    printable = sum(c.isprintable() or c in "\r\n\t" for c in text)
    return printable / max(len(text), 1) >= 0.75 and (len(words) >= 4 or (timecodes and len(words) >= 1))


def read_pmw(file_bytes: bytes) -> str:
    """Read text/XML, ZIP, SQLite, and embedded-text Poliscript PMW variants."""
    import zipfile
    candidates = []
    if file_bytes.startswith(b"PK"):
        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
                for info in archive.infolist():
                    name = info.filename.lower()
                    if not info.is_dir() and info.file_size <= 20 * 1024 * 1024 and name.endswith((".xml", ".json", ".txt", ".srt", ".vtt", ".csv", ".pmw")):
                        candidates.append(decode_bytes(archive.read(info)))
        except (zipfile.BadZipFile, RuntimeError):
            pass
    if file_bytes.startswith(b"SQLite format 3\x00"):
        import os, sqlite3, tempfile
        path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".pmw", delete=False) as tmp:
                tmp.write(file_bytes); path = tmp.name
            db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            rows = []
            for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
                safe_table = table.replace('"', '""')
                try:
                    for row in db.execute(f'SELECT * FROM "{safe_table}"'):
                        values = [str(v).strip() for v in row if isinstance(v, str) and v.strip()]
                        if values: rows.append(" | ".join(values))
                except sqlite3.DatabaseError:
                    continue
            db.close(); candidates.append("\n".join(rows))
        except (OSError, sqlite3.DatabaseError):
            pass
        finally:
            if path:
                try: os.unlink(path)
                except OSError: pass
    candidates.extend([
        decode_bytes(file_bytes),
        "\n".join(m.decode("ascii", errors="ignore") for m in re.findall(rb"[\x20-\x7e]{4,}", file_bytes)),
        "\n".join(m.decode("utf-16-le", errors="ignore") for m in re.findall(rb"(?:[\x20-\x7e]\x00){4,}", file_bytes)),
        "\n".join(m.decode("utf-16-be", errors="ignore") for m in re.findall(rb"(?:\x00[\x20-\x7e]){4,}", file_bytes)),
    ])
    useful = [t.replace("\x00", "") for t in candidates if _useful_pmw_text(t.replace("\x00", ""))]
    if not useful:
        raise UnsupportedPMWError("This PMW file uses a closed, proprietary binary format that cannot be directly decoded. Please export the file as an SRT, VTT, or TXT from your GTS/Iyuno software and upload that instead.")
    def score(text):
        return len(re.findall(r"[^\W\d_]{2,}", text, re.UNICODE)) + 8 * len(re.findall(r"\d{1,2}:\d{2}:\d{2}", text))
    return max(useful, key=score)


def read_docx(file_bytes: bytes) -> str:
    sections = []
    extracted_text = ""
    try:
        from docx import Document
        doc = Document(io.BytesIO(file_bytes))
        paras = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        if paras:
            sections.append("=== PARAGRAPHS ===")
            sections.extend(paras)

        # Some production scripts use one large cell per column and align
        # timecodes/audio with blank paragraphs (instead of using one Word row
        # per cue). ``cell.text`` flattens those columns independently, which
        # destroys their alignment. Keep the last recognised column layout so
        # continuation tables without a repeated header also work.
        stacked_layout = None
        tc_re = re.compile(r"^\d{1,2}[:.]\d{2}[:.]\d{2}(?:[,.:;]\d{1,3})?$")

        def header_role(value: str):
            key = re.sub(r"[^a-z]", "", value.lower())
            if key in {"timecode", "time", "tc", "timein"}:
                return "time"
            if key in {"audio", "dialogue", "dialog", "narration", "speech", "subtitle", "subtitles", "text"}:
                return "dialogue"
            return None

        for i, table in enumerate(doc.tables):
            sections.append(f"\n=== TABLE {i+1} ({len(table.rows)} rows x {len(table.columns)} cols) ===")
            first_values = [c.text.strip() for c in table.rows[0].cells] if table.rows else []
            roles = {header_role(value): idx for idx, value in enumerate(first_values) if header_role(value)}
            first_is_header = "time" in roles and "dialogue" in roles
            if first_is_header:
                stacked_layout = (roles["time"], roles["dialogue"], len(first_values))

            for row_idx, row in enumerate(table.rows):
                if first_is_header and row_idx == 0:
                    sections.append(" | ".join(first_values))
                    continue

                # Rebuild vertically stacked TIME CODE / AUDIO cells into
                # actual cue rows. Each audio paragraph is assigned to the
                # nearest timecode paragraph; deliberate blank-paragraph
                # positioning is therefore retained.
                if stacked_layout and len(row.cells) == stacked_layout[2]:
                    tc_idx, dialogue_idx, column_count = stacked_layout
                    tc_points = [
                        (pi, p.text.strip())
                        for pi, p in enumerate(row.cells[tc_idx].paragraphs)
                        if tc_re.match(p.text.strip())
                    ]
                    dialogue_points = [
                        (pi, p.text.strip())
                        for pi, p in enumerate(row.cells[dialogue_idx].paragraphs)
                        if p.text.strip()
                    ]
                    if tc_points and dialogue_points:
                        grouped = {tc: [] for _, tc in tc_points}
                        if len(tc_points) >= len(dialogue_points):
                            # Usually there is one cue per dialogue, with an
                            # occasional silent/title timecode. Choose the
                            # minimum-distance monotonic one-to-one mapping so
                            # paragraph-count drift cannot merge adjacent cues.
                            n, m = len(tc_points), len(dialogue_points)
                            costs = [[float("inf")] * (m + 1) for _ in range(n + 1)]
                            took = [[False] * (m + 1) for _ in range(n + 1)]
                            for i in range(n + 1):
                                costs[i][0] = 0
                            for i in range(1, n + 1):
                                for j in range(1, min(i, m) + 1):
                                    skip_cost = costs[i - 1][j]
                                    take_cost = costs[i - 1][j - 1] + abs(
                                        tc_points[i - 1][0] - dialogue_points[j - 1][0]
                                    )
                                    if take_cost < skip_cost:
                                        costs[i][j] = take_cost
                                        took[i][j] = True
                                    else:
                                        costs[i][j] = skip_cost
                            choices = []
                            i, j = n, m
                            while j:
                                if took[i][j]:
                                    choices.append(tc_points[i - 1])
                                    i -= 1
                                    j -= 1
                                else:
                                    i -= 1
                            choices.reverse()
                            for (_, tc), (_, dialogue) in zip(choices, dialogue_points):
                                grouped[tc].append(dialogue)
                        else:
                            # More dialogue paragraphs than timecodes means a
                            # cue intentionally contains multiple fragments.
                            for para_idx, dialogue in dialogue_points:
                                _, nearest_tc = min(tc_points, key=lambda point: (abs(point[0] - para_idx), point[0]))
                                grouped[nearest_tc].append(dialogue)
                        for _, tc in tc_points:
                            if not grouped[tc]:
                                continue
                            cells = [""] * column_count
                            cells[tc_idx] = tc
                            cells[dialogue_idx] = " ".join(grouped[tc])
                            sections.append(" | ".join(cells))
                        continue

                cells = []
                seen = set()
                for cell in row.cells:
                    t = cell.text.strip()
                    if t and t not in seen:
                        cells.append(t)
                        seen.add(t)
                if cells:
                    sections.append(" | ".join(cells))
        extracted_text = "\n".join(sections)
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
                extracted_text = "\n".join(lines)
        except:
            raise e

    # OCR fallback — if this DOCX has embedded images (a pasted screenshot
    # of a table instead of a real table, for example) and the normal text
    # extraction above came back thin, OCR the images and append the result
    # rather than silently returning near-nothing for that content.
    try:
        from ocr_reader import ocr_fallback_for_docx
        ocr_text = ocr_fallback_for_docx(file_bytes, len(extracted_text))
        if ocr_text:
            extracted_text = extracted_text + "\n\n=== OCR EXTRACTED CONTENT ===\n" + ocr_text
    except Exception as e:
        print(f"[file_reader] OCR fallback skipped for DOCX: {e}")

    return extracted_text


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
        extracted_text = rtf_to_text(decode_bytes(file_bytes))
    except:
        text = decode_bytes(file_bytes)
        text = re.sub(r'\\[a-zA-Z]+\-?\d*\s?', ' ', text)
        text = re.sub(r'[{}\\]', '', text)
        extracted_text = re.sub(r'\s+', ' ', text).strip()

    # OCR fallback — RTF can embed images via \pict blocks (a pasted
    # screenshot of a table, same category of issue as DOCX/XLSX above,
    # just a structurally different embedding mechanism since RTF isn't a
    # zip archive).
    try:
        from ocr_reader import ocr_fallback_for_rtf
        ocr_text = ocr_fallback_for_rtf(file_bytes, len(extracted_text))
        if ocr_text:
            extracted_text = extracted_text + "\n\n=== OCR EXTRACTED CONTENT ===\n" + ocr_text
    except Exception as e:
        print(f"[file_reader] OCR fallback skipped for RTF: {e}")

    return extracted_text



def list_excel_sheets(file_bytes: bytes) -> list[dict]:
    """
    Return a lightweight list of sheets in an Excel file WITHOUT reading all
    cell content. Each entry: {"name": str, "row_count": int}.
    Used by the /platforms/preview-excel endpoint so the UI can show the
    subtitler which sheets exist before they decide what to import.
    """
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
        sheets = []
        for ws in wb.worksheets:
            try:
                rows = ws.max_row or 0
            except Exception:
                rows = 0
            sheets.append({"name": ws.title, "row_count": rows})
        wb.close()
        return sheets
    except Exception:
        try:
            import xlrd
            wb = xlrd.open_workbook(file_contents=file_bytes)
            return [{"name": s.name, "row_count": s.nrows} for s in wb.sheets()]
        except Exception:
            return []


def read_excel_sheet(file_bytes: bytes, sheet_name: str) -> str:
    """
    Extract text from ONE named sheet of an Excel file, ignoring all other
    sheets completely. This prevents rule bleed-over when a multi-platform
    guidelines workbook is uploaded for a single OTT.

    Returns the sheet content as pipe-delimited rows (same format as
    read_excel, but for a single sheet only).
    """
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
        # Case-insensitive sheet name matching
        sheet = next(
            (ws for ws in wb.worksheets if ws.title.strip().lower() == sheet_name.strip().lower()),
            None
        )
        if sheet is None:
            # Fall back to reading all sheets if the name isn't found
            return read_excel(file_bytes)
        sections = [f"=== SHEET: {sheet.title} ==="]
        for row in sheet.iter_rows(values_only=True):
            cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
            if cells:
                sections.append(" | ".join(cells))
                
        extracted_text = "\n".join(sections)
        # OCR fallback for XLSX
        try:
            from ocr_reader import ocr_fallback_for_xlsx
            ocr_text = ocr_fallback_for_xlsx(file_bytes, len(extracted_text))
            if ocr_text:
                extracted_text = extracted_text + "\n\n=== OCR EXTRACTED CONTENT ===\n" + ocr_text
        except Exception as e:
            print(f"[file_reader] OCR fallback skipped for XLSX sheet: {e}")
        return extracted_text
    except Exception:
        try:
            import xlrd
            wb = xlrd.open_workbook(file_contents=file_bytes)
            sheet = next(
                (s for s in wb.sheets() if s.name.strip().lower() == sheet_name.strip().lower()),
                None
            )
            if sheet is None:
                return read_excel(file_bytes)
            sections = [f"=== SHEET: {sheet.name} ==="]
            for r in range(sheet.nrows):
                cells = [str(sheet.cell_value(r, c)).strip()
                         for c in range(sheet.ncols)
                         if str(sheet.cell_value(r, c)).strip()]
                if cells:
                    sections.append(" | ".join(cells))
            
            extracted_text = "\n".join(sections)
            # OCR fallback for XLS
            try:
                from ocr_reader import ocr_fallback_for_xls
                ocr_text = ocr_fallback_for_xls(file_bytes, len(extracted_text))
                if ocr_text:
                    extracted_text = extracted_text + "\n\n=== OCR EXTRACTED CONTENT ===\n" + ocr_text
            except Exception as e:
                print(f"[file_reader] OCR fallback skipped for XLS sheet: {e}")
            return extracted_text
        except Exception:
            return ""


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
        extracted_text = "\n".join(sections)

        # OCR fallback — XLSX is a zip archive just like DOCX, so a pasted
        # table-as-screenshot (rather than real cell values) is just as
        # possible here and would otherwise come back as an empty sheet
        # with no error to flag it.
        try:
            from ocr_reader import ocr_fallback_for_xlsx
            ocr_text = ocr_fallback_for_xlsx(file_bytes, len(extracted_text))
            if ocr_text:
                extracted_text = extracted_text + "\n\n=== OCR EXTRACTED CONTENT ===\n" + ocr_text
        except Exception as e:
            print(f"[file_reader] OCR fallback skipped for XLSX: {e}")

        return extracted_text
    except:
        # Legacy .xls binary format — NOT a zip archive, so the OCR path
        # above (which relies on zipfile) does not apply here. Falls back
        # to plain text extraction only.
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
        extracted_text = "\n".join(sections)

        # OCR fallback using raw byte scanning for .xls embedded images
        try:
            from ocr_reader import ocr_fallback_for_xls
            ocr_text = ocr_fallback_for_xls(file_bytes, len(extracted_text))
            if ocr_text:
                extracted_text = extracted_text + "\n\n=== OCR EXTRACTED CONTENT ===\n" + ocr_text
        except Exception as e:
            print(f"[file_reader] OCR fallback skipped for XLS: {e}")

        return extracted_text


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
