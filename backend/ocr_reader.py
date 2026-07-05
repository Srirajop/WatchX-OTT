# ocr_reader.py — OCR fallback for guideline documents that are scanned
# images or screenshots pasted into Word/Excel/PDF/RTF instead of real text.
#
# This is exactly the case the company hit with the CAR SOS / Food Factory
# screenshot: a TIME CODE | VISUALS | AUDIO table that's actually a picture
# of a table, not real text — the normal paragraph/cell text readers return
# nothing for it because there IS no text there to read, just pixels.
#
# Covers every format in this project that can structurally contain an
# embedded image:
#   - DOCX  (zip archive, images under word/media/)
#   - XLSX  (zip archive, images under xl/media/ — same OOXML mechanism)
#   - PDF   (embedded image objects, or fully scanned pages)
#   - RTF   (\pict blocks — PNG/JPEG only; \emfblip/\wmetafile vector
#            metafiles are detected but not decoded, see
#            extract_images_from_rtf for why)
#
# NOT covered, deliberately, rather than silently pretending to support them:
#   - Legacy binary .doc / .xls (OLE compound file format, not a zip —
#     extracting embedded images needs a different approach entirely)
# If a guideline document comes in as legacy .doc/.xls with no real text,
# the existing low-text-warning behaviour still applies — it just won't
# auto-OCR. That gap is worth knowing about, not worth pretending is closed.
#
# Used in two places:
#   1. file_reader.py — when reading a script/guideline file and the normal
#      text extraction comes back empty/too-short relative to how many
#      images the document has, OCR the images and append the result.
#   2. guidelines_db.py's bulk-import — when digitizing a new OTT platform's
#      guidelines document that's scanned/screenshotted rather than typed,
#      so the AI extraction step has real text to work with at all.

import io


def extract_images_from_zip_ooxml(file_bytes: bytes, media_path_prefix: str) -> list:
    """
    Shared extractor for any OOXML zip-based format (DOCX, XLSX, PPTX all
    use this same container — only the internal media folder name differs:
    word/media/ for DOCX, xl/media/ for XLSX).
    """
    import zipfile
    images = []
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
            for name in z.namelist():
                if name.startswith(media_path_prefix) and _looks_like_image(name):
                    images.append(z.read(name))
    except Exception as e:
        print(f"[ocr_reader] Could not open as zip for image extraction ({media_path_prefix}): {e}")
    return images


def extract_images_from_docx(file_bytes: bytes) -> list:
    """DOCX embedded images live under word/media/."""
    return extract_images_from_zip_ooxml(file_bytes, "word/media/")


def extract_images_from_xlsx(file_bytes: bytes) -> list:
    """
    XLSX embedded images live under xl/media/ — identical zip-based OOXML
    mechanism to DOCX, just a different folder.
    """
    return extract_images_from_zip_ooxml(file_bytes, "xl/media/")


def extract_images_from_xls(file_bytes: bytes) -> list:
    """
    Legacy .xls is a binary OLE compound format, not a zip archive.
    Instead of using heavy OLE parsing libraries, we use raw byte signature
    scanning (file carving) to find embedded PNG and JPEG data directly within
    the binary stream. This reliably extracts pasted screenshots.
    """
    images = []
    
    # PNG signature: 89 50 4E 47 0D 0A 1A 0A ... IEND (49 45 4E 44 AE 42 60 82)
    png_magic = b'\x89PNG\r\n\x1a\n'
    png_end = b'IEND\xaeB`\x82'
    
    idx = 0
    while True:
        idx = file_bytes.find(png_magic, idx)
        if idx == -1:
            break
        end_idx = file_bytes.find(png_end, idx)
        if end_idx != -1:
            images.append(file_bytes[idx:end_idx + len(png_end)])
            idx = end_idx + len(png_end)
        else:
            break

    # JPEG signature: FF D8 FF ... FF D9
    jpeg_magic = b'\xff\xd8\xff'
    jpeg_end = b'\xff\xd9'
    
    idx = 0
    while True:
        idx = file_bytes.find(jpeg_magic, idx)
        if idx == -1:
            break
        end_idx = file_bytes.find(jpeg_end, idx)
        if end_idx != -1:
            images.append(file_bytes[idx:end_idx + len(jpeg_end)])
            idx = end_idx + len(jpeg_end)
        else:
            break
            
    return images


def extract_images_from_rtf(file_bytes: bytes) -> list:
    """
    RTF embeds images as \\pict control words: a format tag (\\pngblip,
    \\jpegblip, \\emfblip, \\wmetafile, etc.) followed by the image data as
    a long hex string, inside braces: {\\pict\\pngblip\\picw100\\pich50 <hex>...}

    This is a structurally different embedding mechanism from DOCX/XLSX
    (which are zip archives with images as separate files under media/) —
    RTF is a single text stream with image data inlined as hex, so it needs
    its own extraction path rather than reusing extract_images_from_zip_ooxml.

    Only \\pngblip and \\jpegblip are decoded directly (PNG/JPEG, both
    Pillow/Tesseract can read natively). \\emfblip/\\wmetafile (Windows
    vector metafile formats) are detected but not converted — converting
    those would need a different library entirely, and they're rare for
    this pipeline's pasted-screenshot use case, which is virtually always
    PNG or JPEG from a copy-paste, not a vector graphic.
    """
    import re as _re

    text = file_bytes.decode("latin-1", errors="ignore")  # byte-safe for raw hex scanning
    images = []
    skipped_formats = []

    # Find every \pict ... } block. Image data is hex-encoded ASCII, so it's
    # safe to scan within the latin-1 decoded text without corruption.
    pict_blocks = _re.findall(r'\{\\pict(.*?)\}(?=[\s{]|$)', text, _re.DOTALL)

    for block in pict_blocks:
        if r'\pngblip' in block or r'\jpegblip' in block:
            # Strip all RTF control words (\xxx or \xxx123) and whitespace,
            # leaving only the hex digits.
            hex_part = _re.sub(r'\\[a-zA-Z]+-?\d*', '', block)
            hex_part = _re.sub(r'[^0-9a-fA-F]', '', hex_part)
            if len(hex_part) % 2 != 0:
                hex_part = hex_part[:-1]  # malformed trailing nibble — drop it rather than fail
            try:
                img_bytes = bytes.fromhex(hex_part)
                if img_bytes:
                    images.append(img_bytes)
            except ValueError:
                continue  # genuinely corrupt hex data for this one image — skip it, don't crash the whole file
        elif r'\emfblip' in block or r'\wmetafile' in block:
            skipped_formats.append("EMF/WMF vector metafile")

    if skipped_formats:
        print(f"[ocr_reader] RTF has {len(skipped_formats)} vector metafile image(s) — not OCR'd (not a supported format)")

    return images


def extract_images_from_pdf(file_bytes: bytes) -> list:
    """
    Pull embedded raster images out of a PDF using PyMuPDF.
    Handles the case where a guideline page is a scanned image (one big
    image per page) as well as PDFs with several smaller embedded screenshots.
    """
    import fitz  # PyMuPDF
    images = []
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        for page_index in range(len(doc)):
            page = doc[page_index]
            for img in page.get_images(full=True):
                xref = img[0]
                try:
                    base_image = doc.extract_image(xref)
                    images.append(base_image["image"])
                except Exception:
                    continue
        doc.close()
    except Exception as e:
        print(f"[ocr_reader] Could not open PDF for image extraction: {e}")
    return images


def render_pdf_pages_as_images(file_bytes: bytes, dpi: int = 200) -> list:
    """
    Fallback for PDFs where the 'image' covering a page isn't a clean
    embedded image object (e.g. it's actually vector-drawn, or the whole
    page was scanned as one flattened image PyMuPDF doesn't surface via
    get_images). Renders each page to a bitmap directly, guaranteeing we
    always have something to OCR even in awkward PDFs.
    """
    import fitz
    page_images = []
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        zoom = dpi / 72  # PDF default is 72 dpi
        matrix = fitz.Matrix(zoom, zoom)
        for page_index in range(len(doc)):
            pix = doc[page_index].get_pixmap(matrix=matrix)
            page_images.append(pix.tobytes("png"))
        doc.close()
    except Exception as e:
        print(f"[ocr_reader] Could not render PDF pages as images: {e}")
    return page_images


def ocr_image_bytes(image_bytes: bytes) -> str:
    """
    Run OCR on a single image's raw bytes, preserving table column structure.

    Two-tier strategy, in order of reliability:

    1. Grid-line detection (OpenCV): real screenshots of Word/Excel tables
       almost always have visible cell borders. Detecting those lines
       directly and OCR-ing each cell in isolation is deterministic on the
       actual table structure, rather than guessing columns from word-gap
       statistics — which is fragile and varies by font, spacing, and
       image style. This is the case that matters for the CAR SOS/Food
       Factory bug: a real pasted-screenshot table virtually always has
       visible gridlines.

    2. Word-position clustering (fallback): for borderless tables where
       columns are separated by whitespace alone, falls back to grouping
       words by x-position gaps. Less reliable, used only when no grid is
       found, and result quality depends on image layout.

    If neither table structure is found, returns plain OCR text — correct
    behaviour for a non-table image (e.g. a single block of guideline prose).
    """
    from PIL import Image
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode not in ("L", "RGB"):
            img = img.convert("RGB")

        grid_result = _ocr_via_grid_detection(img)
        if grid_result:
            return grid_result

        # No reliable grid found — try word-position clustering as a
        # best-effort fallback for borderless tables.
        import pandas as pd
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DATAFRAME)
        data = data[data.conf != -1].dropna(subset=["text"])
        data = data[data["text"].astype(str).str.strip() != ""]
        if data.empty:
            return ""
        clustered = _reconstruct_table_text(data)
        if clustered and clustered.count("|") > 0:
            return clustered

        # No table structure detected at all — plain prose, plain OCR text.
        return pytesseract.image_to_string(img).strip()

    except Exception as e:
        print(f"[ocr_reader] OCR failed on one image: {e}")
        return ""


def _ocr_via_grid_detection(pil_image) -> str:
    """
    Detect actual table grid lines using OpenCV, derive cell boundaries from
    their intersections, and OCR each cell independently. Returns pipe-
    delimited rows, or empty string if no grid structure was found.
    """
    import cv2
    import numpy as np

    img_array = np.array(pil_image.convert("L"))  # grayscale
    h, w = img_array.shape

    # Binarize: table lines are dark on a light background in virtually
    # every real screenshot of a Word/Excel table.
    _, binary = cv2.threshold(img_array, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # Detect long horizontal and vertical lines specifically — using long,
    # thin structuring elements means short marks (letters, punctuation)
    # don't get picked up as "lines", only genuine table borders do.
    horiz_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(w // 15, 20), 1))
    vert_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(h // 15, 20)))

    horiz_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, horiz_kernel)
    vert_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, vert_kernel)

    row_boundaries = _line_positions_from_mask(horiz_lines, axis=1)
    col_boundaries = _line_positions_from_mask(vert_lines, axis=0)

    # Need at least 2 row boundaries (1 row) and 2 column boundaries
    # (1 column) to call this a real grid — anything less means we didn't
    # actually find a table, just noise.
    if len(row_boundaries) < 2 or len(col_boundaries) < 2:
        return ""

    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    from PIL import Image as PILImage

    rows_text = []
    for ri in range(len(row_boundaries) - 1):
        y0, y1 = row_boundaries[ri], row_boundaries[ri + 1]
        if y1 - y0 < 10:  # too thin to be a real row
            continue
        row_cells = []
        for ci in range(len(col_boundaries) - 1):
            x0, x1 = col_boundaries[ci], col_boundaries[ci + 1]
            if x1 - x0 < 10:
                continue
            # Small inward margin so we don't OCR the border line itself
            cell_img = pil_image.crop((x0 + 3, y0 + 3, max(x1 - 3, x0 + 4), max(y1 - 3, y0 + 4)))
            cell_text = pytesseract.image_to_string(cell_img, config="--psm 7").strip()
            row_cells.append(cell_text)
        if any(c for c in row_cells):
            rows_text.append(" | ".join(row_cells))

    return "\n".join(rows_text)


def _line_positions_from_mask(line_mask, axis: int) -> list:
    """
    Given a binary mask containing only long horizontal or vertical line
    pixels, find the pixel positions of each distinct line by summing
    along the given axis and locating peaks, then merging adjacent peak
    pixels into a single boundary position.
    """
    import numpy as np
    profile = line_mask.sum(axis=axis)
    threshold = profile.max() * 0.5 if profile.max() > 0 else 0
    if threshold == 0:
        return []

    positions = np.where(profile > threshold)[0]
    if len(positions) == 0:
        return []

    # Merge consecutive pixel positions into single boundary points
    boundaries = [int(positions[0])]
    for p in positions[1:]:
        if p - boundaries[-1] > 5:
            boundaries.append(int(p))
        else:
            boundaries[-1] = int((boundaries[-1] + p) / 2)
    return boundaries


def _reconstruct_table_text(word_data) -> str:
    """
    Given Tesseract's per-word bounding-box dataframe, group words into rows
    by their vertical position, then group those rows' words into column
    bands by their horizontal position — producing pipe-delimited lines a
    column-aware parser can split on, instead of one column-blind blob of text.
    """
    rows = {}
    for _, w in word_data.iterrows():
        # Group by (block, paragraph, line) — Tesseract's own row grouping,
        # more reliable than re-deriving rows from raw y-coordinates alone.
        row_key = (int(w["block_num"]), int(w["par_num"]), int(w["line_num"]))
        rows.setdefault(row_key, []).append((int(w["left"]), str(w["text"])))

    line_outputs = []
    all_x_positions = []
    for row_key in sorted(rows.keys()):
        words_in_row = sorted(rows[row_key], key=lambda t: t[0])
        all_x_positions.extend(x for x, _ in words_in_row)

    if not all_x_positions:
        return ""

    # Determine column band boundaries from the gaps between word
    # x-positions across the whole image — a real column break in a table
    # shows up as a consistently large horizontal gap most rows share,
    # which is a more robust signal than guessing a fixed pixel threshold.
    col_boundaries = _detect_column_boundaries(rows)

    for row_key in sorted(rows.keys()):
        words_in_row = sorted(rows[row_key], key=lambda t: t[0])
        if not words_in_row:
            continue

        if col_boundaries:
            columns = [[] for _ in range(len(col_boundaries) + 1)]
            for x, word in words_in_row:
                col_idx = sum(1 for b in col_boundaries if x >= b)
                columns[col_idx].append(word)
            cells = [" ".join(c).strip() for c in columns]
            line_outputs.append(" | ".join(cells))
        else:
            # No reliable column structure detected — fall back to plain
            # space-joined text for this row (e.g. a paragraph, not a table).
            line_outputs.append(" ".join(word for _, word in words_in_row))

    return "\n".join(line_outputs)


def _detect_column_boundaries(rows: dict, min_gap_px: int = 40) -> list:
    """
    Look across all rows for x-position gaps that recur consistently —
    that recurrence is what distinguishes a genuine column boundary from
    just the normal spacing between words within one column's text.
    Returns a sorted list of x-pixel positions to treat as column starts.
    """
    gap_starts = []
    for row_key, words in rows.items():
        sorted_words = sorted(words, key=lambda t: t[0])
        for i in range(1, len(sorted_words)):
            gap = sorted_words[i][0] - sorted_words[i - 1][0]
            if gap >= min_gap_px:
                gap_starts.append(sorted_words[i][0])

    if not gap_starts:
        return []

    # Cluster nearby gap-start positions together (different rows' column
    # starts won't land on the exact same pixel, just close to it).
    gap_starts.sort()
    clusters = []
    current_cluster = [gap_starts[0]]
    for x in gap_starts[1:]:
        if x - current_cluster[-1] <= 30:
            current_cluster.append(x)
        else:
            clusters.append(current_cluster)
            current_cluster = [x]
    clusters.append(current_cluster)

    # Only treat a cluster as a real column boundary if it recurs across
    # a meaningful fraction of rows — a one-off large gap is more likely a
    # mid-sentence formatting quirk than an actual table column.
    total_rows = len(rows)
    min_occurrences = max(2, total_rows // 3)
    boundaries = [
        sum(cluster) // len(cluster)
        for cluster in clusters
        if len(cluster) >= min_occurrences
    ]
    return sorted(boundaries)


def ocr_all_images(images: list) -> str:
    """
    OCR a list of image byte-strings and join the results.
    Skips tiny images (logos, bullet icons, decorative dividers) since
    those produce noise, not guideline content, and waste OCR time.
    """
    sections = []
    for i, img_bytes in enumerate(images):
        if len(img_bytes) < 3000:  # a few KB — too small to be a real screenshot/table
            continue
        text = ocr_image_bytes(img_bytes)
        if text:
            sections.append(f"=== OCR FROM IMAGE {i+1} ===\n{text}")
    return "\n\n".join(sections)


def _looks_like_image(filename: str) -> bool:
    return filename.lower().rsplit(".", 1)[-1] in ("png", "jpg", "jpeg", "bmp", "tiff", "gif", "emf", "wmf")


def _should_run_ocr(images: list, existing_text_length: int) -> bool:
    """
    Shared trigger heuristic across all three formats: if we already
    extracted a healthy amount of real text relative to how many images
    are present, the images are probably just logos/decoration — skip OCR
    (it's slow, roughly 1-3s per image, no reason to pay that cost when a
    real text-based table/paragraph already gave us the content).
    """
    if not images:
        return False
    if existing_text_length > 500 and len(images) <= 2:
        return False
    return True


def ocr_fallback_for_docx(file_bytes: bytes, existing_text_length: int) -> str:
    images = extract_images_from_docx(file_bytes)
    if not _should_run_ocr(images, existing_text_length):
        return ""
    print(f"[ocr_reader] DOCX has {len(images)} embedded image(s), existing text length={existing_text_length} — running OCR")
    return ocr_all_images(images)


def ocr_fallback_for_xlsx(file_bytes: bytes, existing_text_length: int) -> str:
    """
    Same trigger logic as DOCX. This is the path that catches an Excel
    guideline sheet where someone pasted a table as a picture instead of
    typing it into cells — read_excel() would otherwise return that sheet
    as empty or near-empty, with no error to flag it.
    """
    images = extract_images_from_xlsx(file_bytes)
    if not _should_run_ocr(images, existing_text_length):
        return ""
    print(f"[ocr_reader] XLSX has {len(images)} embedded image(s), existing text length={existing_text_length} — running OCR")
    return ocr_all_images(images)


def ocr_fallback_for_xls(file_bytes: bytes, existing_text_length: int) -> str:
    """
    Same trigger logic for legacy .xls files. Uses raw byte scanning to find
    embedded images (PNG/JPEG) since .xls is an OLE compound document rather
    than a ZIP archive like .xlsx.
    """
    images = extract_images_from_xls(file_bytes)
    if not _should_run_ocr(images, existing_text_length):
        return ""
    print(f"[ocr_reader] XLS has {len(images)} embedded image(s), existing text length={existing_text_length} — running OCR")
    return ocr_all_images(images)


def ocr_fallback_for_rtf(file_bytes: bytes, existing_text_length: int) -> str:
    """
    Same trigger logic as DOCX/XLSX, for RTF's \\pict-embedded images.
    Catches the case where an RTF guideline/script document has a pasted
    screenshot (e.g. of a table) rather than real text/table cells.
    """
    images = extract_images_from_rtf(file_bytes)
    if not _should_run_ocr(images, existing_text_length):
        return ""
    print(f"[ocr_reader] RTF has {len(images)} embedded image(s), existing text length={existing_text_length} — running OCR")
    return ocr_all_images(images)


def ocr_fallback_for_pdf(file_bytes: bytes, existing_text_length: int, force_page_render: bool = False) -> str:
    """Same decision logic, but for PDFs — tries embedded images first, falls back to full-page rendering if none are found."""
    images = extract_images_from_pdf(file_bytes)

    if force_page_render:
        print("[ocr_reader] Searchable timings found but dialogue text is missing - rendering PDF pages for OCR")
        images = render_pdf_pages_as_images(file_bytes)
    elif not images and existing_text_length < 200:
        # No embedded image objects AND almost no real text extracted —
        # likely a fully scanned PDF where each page IS the image, not an
        # object inside it. Render pages directly as a last resort.
        print("[ocr_reader] No embedded images found and text is near-empty — rendering PDF pages directly for OCR")
        images = render_pdf_pages_as_images(file_bytes)

    if not _should_run_ocr(images, existing_text_length):
        return ""

    print(f"[ocr_reader] PDF has {len(images)} image(s) to OCR, existing text length={existing_text_length}")
    return ocr_all_images(images)
