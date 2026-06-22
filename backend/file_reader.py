# file_reader.py — Reads ANY subtitle/script file format
# Handles: DOC, DOCX, PDF, SRT, VTT, XML, TTML, RTF, TXT, XLSX, XLS, CSV
# Preserves structure for AI to understand context

import io
import re
import chardet


def read_file(file_bytes: bytes, filename: str) -> dict:
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else "txt"

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
    if "=== TABLE" in text and re.search(r'\d{2}:\d{2}:\d{2}[:;]\d{2}', text):
        return "table_with_timecodes"
    if "COMBINED CONTINUITY" in text or "CCSL" in text.upper() or "SPOTTING LIST" in text.upper():
        return "ccsl_double_dialogue"
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
                            
        return "\n".join(lines).strip()
    except Exception as e:
        print(f"Spire.Doc error: {e}")
        return decode_bytes(file_bytes)
    finally:
        try:
            os.remove(path)
        except:
            pass


def read_pdf(file_bytes: bytes) -> str:
    import PyPDF2
    reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
    pages = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if text.strip():
            pages.append(f"=== PAGE {i+1} ===\n{text}")
    return "\n".join(pages)


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
