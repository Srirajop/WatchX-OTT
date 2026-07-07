# main.py — SubtitleAI V2 Backend
# FastAPI + Groq (LLaMA 3.1 8B Instant) + MySQL

import sys
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv
import os, json, io, re

from database import init_db, get_all_platforms, save_custom_platform, log_job
from file_reader import read_file
from extractor import pre_extract_dialogue
from cleaner import clean_subtitle_chunk, extract_platform_rules_with_ai
from quality_checker import check_quality
from platform_rules import get_platform, get_platform_list
from timecoded_subtitles import ensure_srt_timings, parse_timecoded_subtitles, prepare_for_platform, subtitles_to_srt

load_dotenv()

app = FastAPI(title="SubtitleAI V2", description="AI subtitle cleaning and quality check tool", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_URL", "http://localhost:5173"), "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    try:
        init_db()
    except Exception as e:
        print(f"WARNING DB warning: {e}")
    try:
        from guidelines_db import init_guidelines_table
        init_guidelines_table()
    except Exception as e:
        print(f"WARNING Guidelines DB warning: {e}")


@app.get("/")
def root():
    return {"status": "running", "version": "2.0.0", "model": "llama-3.1-8b-instant"}


@app.get("/health")
def health():
    groq_key = os.getenv("GROQ_API_KEY", "")
    return {
        "status": "ok",
        "groq_configured": bool(groq_key and groq_key != "your_groq_api_key_here"),
        "model": "llama-3.1-8b-instant (Groq)"
    }


# ─── CLEAN ───────────────────────────────────────────────────────

def chunk_text(text: str, max_chunk_size: int = 7000) -> list[str]:
    lines = text.splitlines()
    chunks = []
    current_chunk = []
    current_size = 0
    for line in lines:
        line_len = len(line) + 1
        if current_size + line_len > max_chunk_size and current_chunk:
            chunks.append("\n".join(current_chunk))
            current_chunk = [line]
            current_size = line_len
        else:
            current_chunk.append(line)
            current_size += line_len
    if current_chunk:
        chunks.append("\n".join(current_chunk))
    return chunks


@app.post("/clean")
async def clean_file_endpoint(
    file: UploadFile = File(...),
    platform: str = Form(default="discovery_max"),
    force_ocr: bool = Form(False)
):
    import asyncio
    
    ALLOWED = [".doc",".docx",".pdf",".xml",".ttml",".dfxp",".pmw",
               ".rtf",".srt",".vtt",".webvtt",".xlsx",".xls",
               ".csv",".txt",".json"]

    filename = file.filename or "unknown.txt"
    ext = "." + filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    file_ext = ext.lstrip(".")

    if ext not in ALLOWED:
        raise HTTPException(400, f"File type '{ext}' not supported.")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(400, "Uploaded file is empty")

    try:
        file_data = read_file(file_bytes, filename, force_ocr=force_ocr)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    raw_text = file_data["raw_text"]
    structure = file_data["structure"]

    if not raw_text.strip():
        raise HTTPException(400, "Could not extract text from file")

    # ── Step 1: Pure Python extraction (instant, no LLM) ─────────────────────
    platform_dict = get_platform(platform)
    timecoded_subtitles = parse_timecoded_subtitles(raw_text)

    if timecoded_subtitles and "--- OCR SUBTITLES" not in raw_text:
        async def timecoded_event_generator():
            yield f"data: {json.dumps({'status': 'starting', 'progress': 0, 'message': 'Converting to SRT with original timecodes...'})}\n\n"
            await asyncio.sleep(0.05)

            from quality_checker import auto_fix_subtitles
            for sub in timecoded_subtitles:
                if "original_text" not in sub:
                    sub["original_text"] = sub.get("text", "")
            fixed_subtitles = auto_fix_subtitles(timecoded_subtitles, platform)
            fixed_subtitles = ensure_srt_timings(fixed_subtitles)
            fixed_subtitles = prepare_for_platform(fixed_subtitles, platform, filename)
            for s_idx, sub in enumerate(fixed_subtitles, start=1):
                sub["id"] = s_idx
                sub["start_time"] = normalize_tc(sub.get("start_time", ""))
                sub["end_time"] = normalize_tc(sub.get("end_time", ""))

            total_lines = len(fixed_subtitles)
            flagged_lines = sum(1 for s in fixed_subtitles if s.get("flagged"))
            changed_lines = sum(
                1 for s in fixed_subtitles
                if s.get("original_text", s.get("text", "")).strip() != s.get("text", "").strip()
            )

            try:
                log_job(filename, file_ext, platform, structure, total_lines, flagged_lines, 0)
            except Exception as e:
                print(f"Failed to log job: {e}")

            final_result = {
                "subtitles": fixed_subtitles,
                "stats": {
                    "total_lines": total_lines,
                    "flagged_lines": flagged_lines,
                    "changed_lines": changed_lines,
                    "platform": platform,
                    "detected_structure": "srt_timecoded",
                    "original_format": filename
                }
            }

            yield f"data: {json.dumps({'status': 'completed', 'progress': 100, 'result': final_result})}\n\n"

        return StreamingResponse(
            timecoded_event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            }
        )

    groq_key = os.getenv("GROQ_API_KEY", "")
    if not groq_key or groq_key == "your_groq_api_key_here":
        raise HTTPException(500, "GROQ_API_KEY not configured. Get free key at https://console.groq.com")

    pre_extracted = pre_extract_dialogue(raw_text, structure, file_bytes, filename, platform_dict)

    if pre_extracted:
        # Join extracted lines — LLM only needs to polish punctuation/spelling
        # Much shorter input → much faster LLM response
        clean_input = "\n".join(pre_extracted)
        print(f"[EXTRACT] Pre-extracted {len(pre_extracted)} lines via Python (structure: {structure})")
    else:
        # Fallback: send raw text if extractor found nothing (unusual format)
        clean_input = raw_text
        print(f"[EXTRACT] No pre-extraction, sending raw text to LLM")

    provider = os.getenv("LLM_PROVIDER", "groq").lower()
    # With pre-extraction, input is already clean dialogue.
    # We use optimized chunking to balance TPM limits and throughput.
    lmstudio_chunk = int(os.getenv("LM_STUDIO_CHUNK_SIZE", "1500"))
    chunk_size = lmstudio_chunk if provider == "lmstudio" else 3000
    chunks = chunk_text(clean_input, max_chunk_size=chunk_size)
    total_chunks = len(chunks)
    
    # Process fewer chunks in parallel with larger sizes to prevent exceeding Groq TPM.
    parallel = int(os.getenv("LM_STUDIO_PARALLEL", "1")) if provider == "lmstudio" else 2

    async def process_chunk(idx: int, chunk: str):
        loop = asyncio.get_running_loop()
        return idx, await loop.run_in_executor(
            None,
            clean_subtitle_chunk,
            chunk,
            structure,
            platform,
            filename
        )

    async def event_generator():
        all_subtitles = []

        yield f"data: {json.dumps({'status': 'starting', 'progress': 0, 'message': f'Initializing — {total_chunks} parts, processing {parallel} at a time...'})}\n\n"
        await asyncio.sleep(0.05)

        # Process in parallel batches to match LM Studio's parallel slot count
        for batch_start in range(0, total_chunks, parallel):
            batch = list(enumerate(chunks[batch_start:batch_start + parallel], start=batch_start))
            done = batch_start + len(batch)
            progress_pct = int((batch_start / total_chunks) * 100)
            part_range = f"{batch_start+1}–{done}" if len(batch) > 1 else str(batch_start+1)
            yield f"data: {json.dumps({'status': 'processing', 'progress': progress_pct, 'message': f'AI cleaning parts {part_range} of {total_chunks}...'})}\n\n"
            await asyncio.sleep(0.05)

            try:
                results = await asyncio.gather(*[process_chunk(i, c) for i, c in batch])
                # Sort by original index to preserve document order
                results.sort(key=lambda x: x[0])
                for _, chunk_subs in results:
                    all_subtitles.extend(chunk_subs)
            except Exception as e:
                yield f"data: {json.dumps({'status': 'error', 'error': str(e)})}\n\n"
                return

        # Re-index all subtitles contiguously and assign sequential placeholder timecodes if missing
        from timecoded_subtitles import _from_seconds, _to_seconds
        tc = 0.0
        for s_idx, sub in enumerate(all_subtitles, start=1):
            sub["id"] = s_idx
            
            # If timecodes are missing, generate sequential ones (3s apart) so SRT export works
            if not sub.get("start_time"):
                sub["start_time"] = _from_seconds(tc)
                sub["end_time"] = _from_seconds(tc + 2.0)
                tc += 3.0
            else:
                # Keep existing timecodes, but update 'tc' so any subsequent missing ones continue from here
                parsed = _to_seconds(sub["start_time"])
                if parsed is not None:
                    tc = parsed + 3.0
                if not sub.get("end_time"):
                    sub["end_time"] = _from_seconds(tc - 1.0)

        # ── Auto-fix pass: apply platform rules in Python (100% reliable) ──
        from quality_checker import auto_fix_subtitles
        all_subtitles = auto_fix_subtitles(all_subtitles, platform)

        total_lines = len(all_subtitles)
        flagged_lines = sum(1 for s in all_subtitles if s.get("flagged"))
        # How many lines the AI/auto-fix actually changed vs the raw extracted
        # text — this is the proof-of-work number the subtitler can glance at
        # to confirm cleaning genuinely happened, not just "it ran fast".
        changed_lines = sum(
            1 for s in all_subtitles
            if s.get("original_text", s.get("text", "")).strip() != s.get("text", "").strip()
        )

        # Log job
        try:
            log_job(filename, file_ext, platform, structure, total_lines, flagged_lines, 0)
        except Exception as e:
            print(f"Failed to log job: {e}")

        final_result = {
            "subtitles": all_subtitles,
            "stats": {
                "total_lines": total_lines,
                "flagged_lines": flagged_lines,
                "changed_lines": changed_lines,
                "platform": platform,
                "detected_structure": structure,
                "original_format": filename
            }
        }

        yield f"data: {json.dumps({'status': 'completed', 'progress': 100, 'result': final_result})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",    # disables Nginx/proxy buffering
            "Connection": "keep-alive",
        }
    )

@app.post("/extract")
async def extract_file_endpoint(
    file: UploadFile = File(...),
    platform: str = Form(default="discovery_max"),
    force_ocr: bool = Form(False)
):
    ALLOWED = [".doc",".docx",".pdf",".xml",".ttml",".dfxp",".pmw",
               ".rtf",".srt",".vtt",".webvtt",".xlsx",".xls",
               ".csv",".txt",".json"]

    filename = file.filename or "unknown.txt"
    ext = "." + filename.lower().rsplit(".", 1)[-1] if "." in filename else ""

    if ext not in ALLOWED:
        raise HTTPException(400, f"File type '{ext}' not supported.")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(400, "Uploaded file is empty")

    try:
        file_data = read_file(file_bytes, filename, force_ocr=force_ocr)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    raw_text = file_data["raw_text"]
    structure = file_data["structure"]

    if not raw_text.strip():
        raise HTTPException(400, "Could not extract text from file")

    platform_dict = get_platform(platform)
    timecoded_subtitles = parse_timecoded_subtitles(raw_text)
    if timecoded_subtitles and "--- OCR SUBTITLES" not in raw_text:
        return {
            "subtitles": timecoded_subtitles,
            "stats": {
                "total_lines": len(timecoded_subtitles),
                "flagged_lines": 0,
                "platform": "none",
                "detected_structure": "srt_timecoded",
                "original_format": filename
            }
        }

    pre_extracted = []
    if "--- OCR SUBTITLES" not in raw_text:
        pre_extracted = pre_extract_dialogue(raw_text, structure, file_bytes, filename, platform_dict)
    if not pre_extracted:
        pre_extracted = raw_text.splitlines()

    subtitles = []
    for i, line in enumerate(pre_extracted, 1):
        clean_line = line.strip()
        if clean_line:
            subtitles.append({"id": i, "original_text": clean_line, "text": clean_line, "flagged": False})

    return {
        "subtitles": subtitles,
        "stats": {
            "total_lines": len(subtitles),
            "flagged_lines": 0,
            "platform": "none",
            "detected_structure": structure,
            "original_format": filename
        }
    }


# ─── QUALITY CHECK ───────────────────────────────────────────────

@app.post("/quality-check")
async def quality_check_endpoint(data: dict):
    """
    Check cleaned subtitles for defects before delivery to OTT platform.
    Accepts: { subtitles: [...], platform_key: "...", filename: "..." }
    """
    subtitles = data.get("subtitles", [])
    platform_key = data.get("platform_key", "generic")
    filename = data.get("filename", "subtitles.srt")

    if not subtitles:
        raise HTTPException(400, "No subtitles provided for quality check")

    subtitles = prepare_for_platform(subtitles, platform_key, filename)
    result = check_quality(subtitles, platform_key, filename)

    # Log defects
    try:
        log_job(filename, "quality_check", platform_key, "quality_check",
                result.get("total_lines", 0), 0, result.get("total_defects", 0))
    except Exception:
        pass

    return result


# ─── EXPORT ──────────────────────────────────────────────────────

@app.post("/export/srt")
async def export_srt(data: dict):
    """Export real SRT with preserved timecodes."""
    subtitles = data.get("subtitles", [])
    platform_key = data.get("platform_key", "generic")
    filename = data.get("filename", "cleaned").rsplit(".", 1)[0]

    if not data.get("preserve_exact", False):
        subtitles = prepare_for_platform(subtitles, platform_key, data.get("filename", "cleaned"))
    content = subtitles_to_srt(subtitles)
    if not content.strip():
        raise HTTPException(400, "No timecoded subtitles available for SRT export.")

    buf = io.BytesIO(content.encode("utf-8"))
    return StreamingResponse(buf, media_type="application/x-subrip",
        headers={"Content-Disposition": f"attachment; filename={filename}_cleaned.srt"})


@app.post("/export/txt")
async def export_txt(data: dict):
    subtitles = data.get("subtitles", [])
    filename = data.get("filename", "cleaned").rsplit(".", 1)[0]
    content = "\n".join(s.get("text", "") for s in subtitles if s.get("text"))
    buf = io.BytesIO(content.encode("utf-8"))
    return StreamingResponse(buf, media_type="text/plain",
        headers={"Content-Disposition": f"attachment; filename={filename}_cleaned.txt"})


@app.post("/export/docx")
async def export_docx(data: dict):
    """Export dialogue-only as a DOCX with one paragraph per line and blank spacer between entries."""
    from docx import Document
    from docx.shared import Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    import re
    
    subtitles = data.get("subtitles", [])
    filename = data.get("filename", "cleaned").rsplit(".", 1)[0]

    doc = Document()
    # Set a readable body font
    style = doc.styles["Normal"]
    style.font.name = "Arial"
    style.font.size = Pt(12)

    for i, sub in enumerate(subtitles):
        text = sub.get("text", "").strip()
        if not text:
            continue
        # Remove control characters that break python-docx
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', text)
        # Add the dialogue line, centred to match the screenshot layout
        p = doc.add_paragraph(text)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        # Add a blank spacer paragraph between entries
        if i < len(subtitles) - 1:
            spacer = doc.add_paragraph("")
            spacer.alignment = WD_ALIGN_PARAGRAPH.CENTER

    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return StreamingResponse(buf,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename={filename}_cleaned.docx"})


@app.post("/export/pdf")
async def export_pdf(data: dict):
    """Export dialogue-only as a PDF, centred on the page with spacing between entries."""
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.units import inch
    import html
    import re

    subtitles = data.get("subtitles", [])
    filename = data.get("filename", "cleaned").rsplit(".", 1)[0]

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        leftMargin=1.5 * inch, rightMargin=1.5 * inch,
        topMargin=1 * inch, bottomMargin=1 * inch
    )
    styles = getSampleStyleSheet()
    centred = ParagraphStyle(
        "centred",
        parent=styles["Normal"],
        alignment=TA_CENTER,
        fontSize=12,
        leading=18,
        spaceAfter=0,
    )
    Story = []

    for sub in subtitles:
        text = sub.get("text", "").strip()
        if not text:
            continue
        # Remove control characters
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', text)
        text = html.escape(text).replace("\n", "<br/>")
        Story.append(Paragraph(text, centred))
        # Generous vertical space between each dialogue entry (matches screenshot)
        Story.append(Spacer(1, 28))

    doc.build(Story)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}_cleaned.pdf"})

@app.post("/track-changes")
async def get_track_changes(data: dict):
    """
    Returns track-changes data as JSON for on-screen rendering —
    same comparison logic the PDF export uses, but for display in the UI first.
    The user can review this on screen, then download the PDF report separately.
    """
    from quality_checker import deduce_change_rules

    subtitles = data.get("subtitles", [])
    platform_key = data.get("platform_key", "generic")
    platform_dict = get_platform(platform_key)
    plat_rules = platform_dict.get("rules", [])

    changes = []
    unchanged_count = 0

    for sub in subtitles:
        text = sub.get("text", "").strip()
        orig_text = sub.get("original_text", "").strip()

        if not text and not orig_text:
            continue

        applied_rules = deduce_change_rules(orig_text, text, plat_rules, sub.get("rule_hints", []))

        if not applied_rules:
            unchanged_count += 1
            continue

        changes.append({
            "id": sub.get("id"),
            "original_text": orig_text,
            "new_text": text,
            "rules_applied": applied_rules,
            "flagged": sub.get("flagged", False),
            "flag_reason": sub.get("flag_reason", "")
        })

    return {
        "changes": changes,
        "total_lines": len(subtitles),
        "changed_lines": len(changes),
        "unchanged_lines": unchanged_count,
        "platform": platform_dict.get("name", platform_key)
    }


@app.post("/export/track-changes-pdf")
async def export_track_changes_pdf(data: dict):
    """Export track changes as a PDF, showing original and new text side by side or top to bottom."""
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    from platform_rules import get_platform
    from quality_checker import deduce_change_rules
    import html
    import re

    subtitles = data.get("subtitles", [])
    filename = data.get("filename", "cleaned").rsplit(".", 1)[0]
    platform_key = data.get("platform_key", "generic")
    
    platform_dict = get_platform(platform_key)
    plat_rules = platform_dict.get("rules", [])

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        leftMargin=1 * inch, rightMargin=1 * inch,
        topMargin=1 * inch, bottomMargin=1 * inch
    )
    styles = getSampleStyleSheet()
    
    # Custom styles
    original_style = ParagraphStyle(
        "OriginalText",
        parent=styles["Normal"],
        alignment=TA_LEFT,
        fontSize=10,
        textColor=colors.HexColor("#d97706"),  # orange-ish
        spaceAfter=4,
    )
    new_style = ParagraphStyle(
        "NewText",
        parent=styles["Normal"],
        alignment=TA_LEFT,
        fontSize=11,
        textColor=colors.HexColor("#059669"),  # green-ish
        spaceAfter=4,
    )
    rule_style = ParagraphStyle(
        "RuleText",
        parent=styles["Normal"],
        alignment=TA_LEFT,
        fontSize=9,
        textColor=colors.HexColor("#64748b"),  # slate gray
        spaceAfter=12,
        leftIndent=10,
    )

    Story = []
    
    # Title
    title_style = ParagraphStyle("TitleStyle", parent=styles["Heading1"], alignment=TA_LEFT, spaceAfter=16)
    Story.append(Paragraph(f"Track Changes: {filename}", title_style))
    Story.append(Spacer(1, 12))

    for sub in subtitles:
        text = sub.get("text", "").strip()
        orig_text = sub.get("original_text", "").strip()
        
        if not text and not orig_text:
            continue
            
        # Same logic the on-screen Track Changes view uses — kept identical on purpose
        applied_rules = deduce_change_rules(orig_text, text, plat_rules, sub.get("rule_hints", []))
            
        # Remove control characters
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', text)
        orig_text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', orig_text)
        
        text_safe = html.escape(text).replace("\n", "<br/>")
        orig_safe = html.escape(orig_text).replace("\n", "<br/>")

        Story.append(Paragraph(f"<b>Previously:</b> {orig_safe}", original_style))
        Story.append(Paragraph(f"<b>Cleaned:</b> {text_safe}", new_style))
        
        if applied_rules:
            rules_html = "<b>Rules Applied:</b><br/>" + "<br/>".join(f"• {r}" for r in applied_rules)
            Story.append(Paragraph(rules_html, rule_style))
        else:
            Story.append(Spacer(1, 8))

    doc.build(Story)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}_track_changes.pdf"})


@app.post("/adjust-timecodes")
async def adjust_timecodes_endpoint(data: dict):
    """
    Manual timecode correction tool — for the subtitler to fix a timecode
    they know is wrong (e.g. footage drift), without touching audio/video.
    Four modes:
      offset            — shift EVERY subtitle in the file by a fixed amount
      shift_only_this   — fix ONE subtitle's start/end, every other line untouched
      fix_from_index    — fix one subtitle, ripple the same shift to EVERY subtitle after it (to the end of the file)
      fix_range         — fix one subtitle, ripple the same shift only up to a chosen end ID (a bounded section, not the whole rest of the file) — use this when drift only affects a stretch of the file that re-syncs correctly later on
    """
    from timecode_adjuster import shift_timecodes, fix_from_index, fix_range_from_index, shift_only_this, parse_offset_input, sync_target

    subtitles = data.get("subtitles", [])
    mode = data.get("mode", "offset")

    if not subtitles:
        raise HTTPException(400, "No subtitles provided")

    if mode == "offset":
        offset_seconds = parse_offset_input(data.get("value", ""))
        if offset_seconds is None:
            raise HTTPException(400, "Could not parse offset value. Use a format like '+1.5s' or '-0:00:02'")
        result = shift_timecodes(subtitles, offset_seconds)
        return {"subtitles": result, "total": len(result), "value": data.get("value", "")}

    elif mode == "shift_only_this":
        target_id = data.get("target_id")
        new_start = data.get("new_start", "")
        new_end = data.get("new_end", "")
        if target_id is None:
            raise HTTPException(400, "target_id is required")
        result = shift_only_this(subtitles, target_id, new_start, new_end)
        return {"subtitles": result["subtitles"], "collision": result["collision"], "collision_detail": result["collision_detail"]}

    elif mode == "fix_from_index":
        target_id = data.get("target_id")
        new_tc = data.get("value", "")
        if target_id is None:
            raise HTTPException(400, "target_id is required")
        result = fix_from_index(subtitles, target_id, new_tc)
        return {"subtitles": result, "total": len(result)}

    elif mode == "fix_range":
        target_id = data.get("target_id")
        range_end_id = data.get("range_end_id")
        new_tc = data.get("value", "")
        if target_id is None or range_end_id is None:
            raise HTTPException(400, "Both target_id and range_end_id are required for fix_range mode")
        result = fix_range_from_index(subtitles, target_id, new_tc, range_end_id)
        return {
            "subtitles": result["subtitles"],
            "touched_ids": result["touched_ids"],
            "warning": result["warning"],
        }

    elif mode == "sync_target":
        target_id = data.get("target_id", 1)
        new_start = data.get("new_start", "")
        new_end = data.get("new_end", "")
        shift_mode = data.get("shift_mode", "all")
        result = sync_target(subtitles, target_id, new_start, new_end, shift_mode)
        return {
            "subtitles": result["subtitles"],
            "collision": result["collision"],
            "collision_detail": result["collision_detail"],
            "warning": result["warning"]
        }

    else:
        raise HTTPException(400, f"Unknown mode '{mode}'. Use offset, shift_only_this, fix_from_index, or fix_range.")



# ─── PLATFORMS ───────────────────────────────────────────────────

@app.get("/platforms")
def get_platforms():
    try:
        platforms = get_all_platforms()
        return {"platforms": platforms}
    except:
        # Fallback to static list if DB not ready
        return {"platforms": {p["key"]: p for p in get_platform_list()}}



@app.post("/platforms/add")
async def add_platform(
    platform_name: str = Form(...),
    version_label: str = Form(default="Current"),
    sheet_name: str = Form(default=""),          # optional: target a specific Excel sheet
    guidelines_file: UploadFile = File(None),
    guidelines_text: str = Form(default="")
):
    if not platform_name.strip():
        raise HTTPException(400, "Platform name is required")

    version_slug = re.sub(r'[^a-z0-9]', '_', (version_label or 'current').lower().strip()).strip('_')
    platform_family = "custom_" + re.sub(r'[^a-z0-9]', '_', platform_name.lower().strip())
    platform_key = f"{platform_family}__{version_slug}"

    raw_guidelines = ""
    if guidelines_file and guidelines_file.filename:
        file_bytes = await guidelines_file.read()
        if not file_bytes:
            raise HTTPException(400, "Uploaded guidelines file is empty")

        ext = guidelines_file.filename.lower().rsplit(".", 1)[-1]
        if sheet_name.strip() and ext in ("xlsx", "xls"):
            # ── SHEET-SPECIFIC extraction: isolate one sheet from the workbook ──
            from file_reader import read_excel_sheet
            raw_guidelines = read_excel_sheet(file_bytes, sheet_name.strip())
            print(f"[PLATFORMS] Read sheet '{sheet_name}' → {len(raw_guidelines)} chars")
        else:
            file_data = read_file(file_bytes, guidelines_file.filename)
            raw_guidelines = file_data["raw_text"]
            print(f"[PLATFORMS] Read {len(raw_guidelines)} chars from '{guidelines_file.filename}'")
    elif guidelines_text.strip():
        raw_guidelines = guidelines_text.strip()

    if not raw_guidelines.strip():
        raise HTTPException(400, "No readable text found in the uploaded document. "
                            "Please try a different format (PDF, DOCX, TXT).")

    print(f"[PLATFORMS] Extracting rules for '{platform_name}' v'{version_label}' from {len(raw_guidelines)} chars")
    platform_data = extract_platform_rules_with_ai(raw_guidelines, platform_name.strip())

    platform_data["platform_family"] = platform_family
    platform_data["version_label"]   = version_label.strip() or "Current"
    platform_data["guidelines_raw"]  = raw_guidelines

    save_custom_platform(platform_key, platform_data)

    rules_count = len(platform_data.get("rules", []))
    print(f"[PLATFORMS] Saved '{platform_name}' ({version_label}) as '{platform_key}' with {rules_count} rules")

    return {
        "success": True,
        "platform_key": platform_key,
        "platform_family": platform_family,
        "version_label": platform_data["version_label"],
        "platform_name": platform_name.strip(),
        "rules_extracted": rules_count,
        "message": f"Platform '{platform_name}' ({platform_data['version_label']}) saved with {rules_count} rules extracted"
    }


@app.post("/platforms/preview-excel")
async def preview_excel_sheets(guidelines_file: UploadFile = File(...)):
    """
    Return the list of sheet names (+ row counts) from an uploaded Excel file
    WITHOUT extracting any rules. Used by the bulk-import UI so subtitlers
    can see what sheets exist and map each one to a platform name/version.
    """
    file_bytes = await guidelines_file.read()
    if not file_bytes:
        raise HTTPException(400, "File is empty")
    ext = guidelines_file.filename.lower().rsplit(".", 1)[-1]
    if ext not in ("xlsx", "xls"):
        raise HTTPException(400, "Only Excel (.xlsx / .xls) files are supported for sheet preview")
    from file_reader import list_excel_sheets
    sheets = list_excel_sheets(file_bytes)
    if not sheets:
        raise HTTPException(422, "Could not read any sheets from this file")
    return {"filename": guidelines_file.filename, "sheets": sheets}


@app.post("/platforms/bulk-add")
async def bulk_add_platforms(
    guidelines_file: UploadFile = File(...),
    mappings: str = Form(...)   # JSON string: [{sheet_name, platform_name, version_label}]
):
    """
    Process a multi-sheet Excel file and import each mapped sheet as a
    separate platform version in one request.

    mappings example:
    [
      {"sheet_name": "Netflix",      "platform_name": "Netflix",      "version_label": "Current"},
      {"sheet_name": "Discovery Max","platform_name": "Discovery Max","version_label": "2023 Guidelines"}
    ]
    """
    import json as _json
    try:
        mapping_list = _json.loads(mappings)
    except Exception:
        raise HTTPException(400, "Invalid mappings JSON")

    file_bytes = await guidelines_file.read()
    if not file_bytes:
        raise HTTPException(400, "File is empty")

    from file_reader import read_excel_sheet

    results = []
    for entry in mapping_list:
        sheet   = entry.get("sheet_name", "").strip()
        p_name  = entry.get("platform_name", "").strip()
        version = entry.get("version_label", "Current").strip() or "Current"

        if not sheet or not p_name:
            results.append({"sheet_name": sheet, "status": "skipped", "reason": "Missing sheet or platform name"})
            continue

        try:
            raw = read_excel_sheet(file_bytes, sheet)
            if not raw.strip():
                results.append({"sheet_name": sheet, "platform_name": p_name, "status": "skipped",
                                 "reason": "Sheet is empty or could not be read"})
                continue

            version_slug   = re.sub(r'[^a-z0-9]', '_', version.lower()).strip('_')
            platform_family = "custom_" + re.sub(r'[^a-z0-9]', '_', p_name.lower())
            platform_key    = f"{platform_family}__{version_slug}"

            print(f"[BULK] Processing sheet '{sheet}' → '{p_name}' ({version}) — {len(raw)} chars")
            platform_data = extract_platform_rules_with_ai(raw, p_name)
            platform_data["platform_family"] = platform_family
            platform_data["version_label"]   = version
            platform_data["guidelines_raw"]  = raw

            save_custom_platform(platform_key, platform_data)
            rules_count = len(platform_data.get("rules", []))

            results.append({
                "sheet_name": sheet,
                "platform_name": p_name,
                "version_label": version,
                "platform_key": platform_key,
                "rules_extracted": rules_count,
                "status": "ok"
            })
        except Exception as e:
            results.append({"sheet_name": sheet, "platform_name": p_name, "status": "error", "reason": str(e)})

    ok = [r for r in results if r.get("status") == "ok"]
    return {
        "total": len(mapping_list),
        "imported": len(ok),
        "results": results,
        "message": f"Imported {len(ok)} of {len(mapping_list)} platforms from '{guidelines_file.filename}'"
    }


@app.delete("/platforms/{platform_key}")
def delete_platform(platform_key: str):
    from database import get_connection
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM platforms WHERE platform_key=%s", (platform_key,))
    affected = cursor.rowcount
    conn.commit()
    cursor.close()
    conn.close()
    if affected == 0:
        raise HTTPException(404, "Platform not found")
    return {"success": True}


@app.delete("/platforms/family/{family_key}")
def delete_platform_family(family_key: str):
    """Delete ALL versions of a platform family at once."""
    from database import get_connection
    conn = get_connection()
    cursor = conn.cursor()
    # Match by family key OR by platform_key prefix (covers built-ins which use key as family)
    cursor.execute(
        "DELETE FROM platforms WHERE platform_family=%s OR platform_key=%s",
        (family_key, family_key)
    )
    affected = cursor.rowcount
    conn.commit()
    cursor.close()
    conn.close()
    if affected == 0:
        raise HTTPException(404, "No versions found for this platform family")
    return {"success": True, "deleted_versions": affected}


@app.patch("/platforms/{platform_key}/meta")
async def update_platform_meta(platform_key: str, data: dict):
    """
    Update name, version_label, and/or rules for one platform version.
    Works on any platform (built-in or custom).
    """
    import json as _json
    from database import get_connection

    name          = data.get("name")
    version_label = data.get("version_label")
    rules         = data.get("rules")
    subtitler_rules = data.get("subtitler_rules")

    if not any([name, version_label is not None, rules is not None, subtitler_rules is not None]):
        raise HTTPException(400, "Nothing to update — provide name, version_label, rules, or subtitler_rules")

    conn   = get_connection()
    cursor = conn.cursor()

    parts  = []
    params = []
    if name is not None:
        parts.append("name=%s");          params.append(name.strip())
    if version_label is not None:
        parts.append("version_label=%s"); params.append(version_label.strip())
    if rules is not None:
        if not isinstance(rules, list):
            raise HTTPException(400, "Rules must be an array")
        parts.append("rules=%s");         params.append(_json.dumps(rules))
    if subtitler_rules is not None:
        if not isinstance(subtitler_rules, list):
            raise HTTPException(400, "Subtitler rules must be an array")
        parts.append("subtitler_rules=%s"); params.append(_json.dumps(subtitler_rules))

    params.append(platform_key)
    cursor.execute(f"UPDATE platforms SET {', '.join(parts)} WHERE platform_key=%s", params)
    affected = cursor.rowcount
    conn.commit()
    cursor.close()
    conn.close()

    if affected == 0:
        raise HTTPException(404, "Platform not found")
    return {"success": True, "platform_key": platform_key}


@app.patch("/platforms/family/{family_key}/name")
async def rename_platform_family(family_key: str, data: dict):
    """
    Rename the display name for ALL versions of a platform family at once.
    e.g. 'Nickelodeon V10' → 'Nickelodeon' across every version in the group.
    """
    new_name = (data.get("name") or "").strip()
    if not new_name:
        raise HTTPException(400, "New name is required")

    from database import get_connection
    conn   = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE platforms SET name=%s WHERE platform_family=%s OR platform_key=%s",
        (new_name, family_key, family_key)
    )
    affected = cursor.rowcount
    conn.commit()
    cursor.close()
    conn.close()

    if affected == 0:
        raise HTTPException(404, "Platform family not found")
    return {"success": True, "family_key": family_key, "new_name": new_name, "updated": affected}



# ─── HELPER ──────────────────────────────────────────────────────

def normalize_tc(tc: str) -> str:
    if not tc:
        return ""
    tc = tc.strip()
    if re.match(r'\d{2}:\d{2}:\d{2},\d{3}', tc):
        return tc
    m = re.match(r'(\d{2}):(\d{2}):(\d{2})[:;](\d{2})', tc)
    if m:
        h, mn, s, f = m.groups()
        ms = int(int(f) * 1000 / 25)
        return f"{h}:{mn}:{s},{ms:03d}"
    m = re.match(r'(\d{2}):(\d{2}):(\d{2})\.(\d+)', tc)
    if m:
        h, mn, s, ms = m.groups()
        return f"{h}:{mn}:{s},{ms[:3].ljust(3,'0')}"
    return tc



# ─── OTT GUIDELINES SEARCH ENGINE ───────────────────────────────────
#
# Matches the company's own mockup (June_26_2026_OTT_Guidelines_SearchEngine.pptx):
# keyword search + Client/Platform/Category/Year filters over a flat,
# searchable table of digitized guideline spec rows. Separate concern from
# the AI cleaner's platform rules — this is for humans looking things up,
# not for the cleaner consuming numeric limits.

@app.get("/guidelines/search")
def search_guidelines_endpoint(
    keyword: str = "",
    client: str = "",
    ott_platform: str = "",
    category: str = "",
    year: int = None,
    include_all_versions: bool = False,
):
    from guidelines_db import search_guidelines
    try:
        results = search_guidelines(keyword, client, ott_platform, category, year, include_all_versions)
        return {"results": results, "total": len(results)}
    except Exception as e:
        raise HTTPException(500, f"Guidelines search failed: {e}")


@app.get("/guidelines/filters")
def get_guidelines_filters():
    """Returns the live distinct values for every filter dropdown, so the UI never shows a stale hardcoded list."""
    from guidelines_db import get_filter_options
    try:
        return get_filter_options()
    except Exception as e:
        raise HTTPException(500, f"Could not load filter options: {e}")


@app.post("/guidelines/add")
async def add_guideline_endpoint(data: dict):
    from guidelines_db import add_guideline
    required = ["client", "ott_platform", "spec", "guideline", "year"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        raise HTTPException(400, f"Missing required field(s): {', '.join(missing)}")
    try:
        new_id = add_guideline(data)
        return {"success": True, "id": new_id}
    except Exception as e:
        raise HTTPException(500, f"Could not add guideline: {e}")


@app.put("/guidelines/{guideline_id}")
async def update_guideline_endpoint(guideline_id: int, data: dict):
    """
    Updating a guideline does NOT overwrite it — it creates a new version
    and marks the old one superseded (but keeps it queryable). See
    guidelines_db.update_guideline() for why: old projects need to be able
    to look up the rules that were in force when THEY were built.
    """
    from guidelines_db import update_guideline, search_guidelines
    try:
        success = update_guideline(guideline_id, data)
        if not success:
            raise HTTPException(404, "Guideline not found")
        return {"success": True, "note": "Previous version preserved in history, not overwritten."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Could not update guideline: {e}")


@app.get("/guidelines/{guideline_id}/history")
def get_guideline_history_endpoint(guideline_id: int):
    """
    Returns every version of a guideline (oldest first), given any single
    version's id. Lets the UI show 'this rule changed 3 times' and lets
    someone pick an older version for an older project.
    """
    from guidelines_db import get_guideline_history
    try:
        history = get_guideline_history(guideline_id)
        if not history:
            raise HTTPException(404, "Guideline not found")
        return {"history": history, "total_versions": len(history)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Could not load guideline history: {e}")


@app.delete("/guidelines/{guideline_id}")
def delete_guideline_endpoint(guideline_id: int, hard_delete: bool = False):
    """
    By default this is a soft delete — marks the entry as no longer
    current, but the row and its history remain in the database. Pass
    hard_delete=true only to genuinely remove a mistaken/garbage entry.
    """
    from guidelines_db import delete_guideline
    try:
        success = delete_guideline(guideline_id, hard_delete=hard_delete)
        if not success:
            raise HTTPException(404, "Guideline not found")
        return {"success": True, "hard_deleted": hard_delete}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Could not delete guideline: {e}")


@app.post("/guidelines/bulk-import")
async def bulk_import_guidelines(
    client: str = Form(...),
    ott_platform: str = Form(...),
    year: int = Form(...),
    guidelines_file: UploadFile = File(None),
    guidelines_text: str = Form(default=""),
):
    """
    Digitize a whole guidelines document in one step — upload the original
    PDF/DOC/XLSX (or paste raw text) and the AI splits it into individual
    structured spec rows, exactly like the company manually did to build the
    'Sample Data Collation' table in their own mockup deck. This is what
    makes adding a brand-new OTT platform's guidelines fast instead of
    someone typing each row in by hand.
    """
    from guidelines_db import extract_guidelines_with_ai, add_guideline

    raw_text = ""
    if guidelines_file and guidelines_file.filename:
        file_bytes = await guidelines_file.read()
        raw_text = read_file(file_bytes, guidelines_file.filename)["raw_text"]
    elif guidelines_text.strip():
        raw_text = guidelines_text.strip()

    if not raw_text:
        raise HTTPException(400, "Provide either a file or pasted guideline text")

    try:
        entries = extract_guidelines_with_ai(raw_text, client, ott_platform, year)
    except Exception as e:
        raise HTTPException(500, f"AI extraction failed: {e}")

    added_ids = []
    for entry in entries:
        try:
            added_ids.append(add_guideline(entry))
        except Exception as e:
            print(f"[bulk-import] Skipped one row due to error: {e}")

    return {
        "success": True,
        "entries_extracted": len(entries),
        "entries_added": len(added_ids),
        "ids": added_ids,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


# ─── TRANSCRIBE ──────────────────────────────────────────────

@app.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    import tempfile
    import os
    import json
    import threading
    import queue
    import asyncio
    from timecoded_subtitles import _from_seconds

    filename = file.filename or "audio.webm"
    
    # Save the uploaded file to a temporary location for faster-whisper
    with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    async def transcribe_stream():
        yield f"data: {json.dumps({'status': 'starting', 'message': 'Initializing transcription engine...', 'progress': 0})}\n\n"
        await asyncio.sleep(0.05)
        
        q = queue.Queue()
        
        def worker():
            try:
                from faster_whisper import WhisperModel
                q.put({"type": "status", "message": "Loading AI model into memory (might download on first run)...", "progress": 5})
                # "base" provides a great balance of speed and accuracy for local CPUs.
                model = WhisperModel("base", device="cpu", compute_type="int8")
                
                q.put({"type": "status", "message": "Analyzing audio stream...", "progress": 10})
                segments, info = model.transcribe(tmp_path, beam_size=5, word_timestamps=False)
                
                duration = info.duration
                if duration <= 0: duration = 1.0
                
                q.put({"type": "status", "message": "Transcribing audio...", "progress": 15})
                
                subs = []
                for i, segment in enumerate(segments, start=1):
                    subs.append({
                        "id": i,
                        "start_time": _from_seconds(segment.start),
                        "end_time": _from_seconds(segment.end),
                        "text": segment.text.strip(),
                        "flagged": False,
                        "flag_reason": ""
                    })
                    pct = min(95, int(15 + (segment.end / duration) * 80))
                    q.put({"type": "status", "message": f"Transcribing... ({int(segment.end)}s / {int(duration)}s)", "progress": pct})
                    
                q.put({"type": "done", "subtitles": subs})
            except Exception as e:
                q.put({"type": "error", "error": str(e)})

        thread = threading.Thread(target=worker)
        thread.start()
        
        while True:
            try:
                msg = q.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.1)
                continue
                
            if msg["type"] == "status":
                yield f"data: {json.dumps({'status': 'processing', 'message': msg['message'], 'progress': msg['progress']})}\n\n"
            elif msg["type"] == "error":
                yield f"data: {json.dumps({'status': 'error', 'error': msg['error']})}\n\n"
                break
            elif msg["type"] == "done":
                result = {
                    "subtitles": msg["subtitles"],
                    "stats": {
                        "total_lines": len(msg["subtitles"]),
                        "flagged_lines": 0,
                        "platform": "none",
                        "detected_structure": "local_whisper_audio",
                        "original_format": filename
                    }
                }
                yield f"data: {json.dumps({'status': 'completed', 'progress': 100, 'result': result})}\n\n"
                break
                
        # Clean up temporary file
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    return StreamingResponse(
        transcribe_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )

@app.post("/transcribe-and-align")
async def transcribe_and_align_endpoint(
    audio: UploadFile = File(...),
    script: UploadFile = File(None),
    platform: str = Form(default="generic")
):
    import tempfile
    import os
    import json
    import threading
    import queue
    import asyncio
    from timecoded_subtitles import _from_seconds
    from platform_rules import get_platform
    from file_reader import read_file
    from extractor import pre_extract_dialogue
    from transcript_aligner import align_transcription_to_script

    filename = audio.filename or "audio.webm"
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as tmp:
        content = await audio.read()
        tmp.write(content)
        tmp_path = tmp.name

    # Pre-process script if provided
    script_subs = []
    if script:
        script_bytes = await script.read()
        script_name = script.filename or "script.txt"
        file_data = read_file(script_bytes, script_name)
        raw_text = file_data["raw_text"]
        structure = file_data["structure"]
        
        platform_dict = get_platform(platform)
        pre_extracted = pre_extract_dialogue(raw_text, structure, script_bytes, script_name, platform_dict)
        if not pre_extracted:
            pre_extracted = raw_text.splitlines()

        for i, line in enumerate(pre_extracted, 1):
            clean_line = line.strip()
            if clean_line:
                script_subs.append({"id": i, "text": clean_line, "flagged": False})

    async def transcribe_align_stream():
        yield f"data: {json.dumps({'status': 'starting', 'message': 'Initializing transcription engine...', 'progress': 0})}\n\n"
        await asyncio.sleep(0.05)
        
        q = queue.Queue()
        
        def worker():
            try:
                from faster_whisper import WhisperModel
                q.put({"type": "status", "message": "Loading AI model into memory...", "progress": 5})
                model = WhisperModel("base", device="cpu", compute_type="int8")
                
                q.put({"type": "status", "message": "Analyzing audio stream...", "progress": 10})
                segments, info = model.transcribe(tmp_path, beam_size=5, word_timestamps=False)
                
                duration = info.duration
                if duration <= 0: duration = 1.0
                
                q.put({"type": "status", "message": "Transcribing audio...", "progress": 15})
                
                whisper_subs = []
                for i, segment in enumerate(segments, start=1):
                    whisper_subs.append({
                        "id": i,
                        "start_time": _from_seconds(segment.start),
                        "end_time": _from_seconds(segment.end),
                        "text": segment.text.strip(),
                        "flagged": False,
                        "flag_reason": ""
                    })
                    pct = min(90, int(15 + (segment.end / duration) * 75))
                    q.put({"type": "status", "message": f"Transcribing... ({int(segment.end)}s / {int(duration)}s)", "progress": pct})
                    
                if script_subs:
                    q.put({"type": "status", "message": "Aligning timecodes to script...", "progress": 95})
                    final_subs = align_transcription_to_script(whisper_subs, script_subs)
                else:
                    final_subs = whisper_subs
                    
                q.put({"type": "done", "subtitles": final_subs})
            except Exception as e:
                err_msg = str(e)
                if "tuple index out of range" in err_msg:
                    err_msg = "Could not extract audio from the uploaded file. It might be a video with no audio track, or an unsupported codec."
                q.put({"type": "error", "error": err_msg})

        thread = threading.Thread(target=worker)
        thread.start()
        
        while True:
            try:
                msg = q.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.1)
                continue
                
            if msg["type"] == "status":
                yield f"data: {json.dumps({'status': 'processing', 'message': msg['message'], 'progress': msg['progress']})}\n\n"
            elif msg["type"] == "error":
                yield f"data: {json.dumps({'status': 'error', 'error': msg['error']})}\n\n"
                break
            elif msg["type"] == "done":
                result = {
                    "subtitles": msg["subtitles"],
                    "stats": {
                        "total_lines": len(msg["subtitles"]),
                        "flagged_lines": sum(1 for s in msg["subtitles"] if s.get("flagged")),
                        "platform": platform,
                        "detected_structure": "aligned_script" if script_subs else "whisper_audio",
                        "original_format": filename
                    }
                }
                yield f"data: {json.dumps({'status': 'completed', 'progress': 100, 'result': result})}\n\n"
                break
                
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    return StreamingResponse(
        transcribe_align_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )

@app.post("/align-scripts")
async def align_scripts_endpoint(
    script_file: UploadFile = File(...),
    timestamps_file: UploadFile = File(...)
):
    from file_reader import read_file
    from extractor import pre_extract_dialogue
    from timecoded_subtitles import parse_timecoded_subtitles
    from transcript_aligner import align_transcription_to_script
    import asyncio
    
    script_bytes = await script_file.read()
    script_name = script_file.filename or "script.txt"
    script_data = read_file(script_bytes, script_name)
    script_raw = script_data["raw_text"]
    script_structure = script_data["structure"]
    
    pre_extracted = pre_extract_dialogue(script_raw, script_structure, script_bytes, script_name, {})
    if not pre_extracted:
        pre_extracted = script_raw.splitlines()
        
    script_subs = []
    for i, line in enumerate(pre_extracted, 1):
        clean_line = line.strip()
        if clean_line:
            script_subs.append({"id": i, "text": clean_line, "flagged": False})

    ts_bytes = await timestamps_file.read()
    ts_name = timestamps_file.filename or "timestamps.srt"
    ts_data = read_file(ts_bytes, ts_name)
    ts_raw = ts_data["raw_text"]
    
    ts_subs = parse_timecoded_subtitles(ts_raw)
    if not ts_subs:
        raise HTTPException(400, "Could not extract timecodes from the timestamps file.")

    final_subs = align_transcription_to_script(ts_subs, script_subs)

    return {
        "subtitles": final_subs,
        "stats": {
            "total_lines": len(final_subs),
            "flagged_lines": sum(1 for s in final_subs if s.get("flagged")),
            "platform": "generic",
            "detected_structure": "aligned_scripts",
            "original_format": script_name
        }
    }

# ─── MOVIES ──────────────────────────────────────────────────────

from pydantic import BaseModel

class MovieAddRequest(BaseModel):
    title: str
    url: str
    added_by: str = "Anonymous"

@app.get("/movies")
def get_movies():
    try:
        from database import get_all_movies
        return {"movies": get_all_movies()}
    except Exception as e:
        print(f"Error fetching movies: {e}")
        return {"movies": []}

@app.post("/movies")
def add_new_movie(req: MovieAddRequest):
    if not req.title.strip() or not req.url.strip():
        raise HTTPException(400, "Title and URL are required")
    if not re.match(r"^https?://[^\s]+$", req.url.strip(), re.IGNORECASE):
        raise HTTPException(400, "URL must start with http:// or https://")
    try:
        from database import add_movie
        add_movie(req.title.strip(), req.url.strip(), req.added_by.strip() or "Anonymous")
        return {"message": "Movie added successfully"}
    except Exception as e:
        print(f"Error adding movie: {e}")
        raise HTTPException(500, "Failed to add movie")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
