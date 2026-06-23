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
    platform: str = Form(default="discovery_max")
):
    import asyncio
    
    ALLOWED = [".doc",".docx",".pdf",".xml",".ttml",".dfxp",
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

    file_data = read_file(file_bytes, filename)
    raw_text = file_data["raw_text"]
    structure = file_data["structure"]

    if not raw_text.strip():
        raise HTTPException(400, "Could not extract text from file")

    # ── Step 1: Pure Python extraction (instant, no LLM) ─────────────────────
    platform_dict = get_platform(platform)
    timecoded_subtitles = parse_timecoded_subtitles(raw_text)

    if timecoded_subtitles:
        async def timecoded_event_generator():
            yield f"data: {json.dumps({'status': 'starting', 'progress': 0, 'message': 'Converting to SRT with original timecodes...'})}\n\n"
            await asyncio.sleep(0.05)

            from quality_checker import auto_fix_subtitles
            fixed_subtitles = auto_fix_subtitles(timecoded_subtitles, platform)
            fixed_subtitles = ensure_srt_timings(fixed_subtitles)
            fixed_subtitles = prepare_for_platform(fixed_subtitles, platform, filename)
            for s_idx, sub in enumerate(fixed_subtitles, start=1):
                sub["id"] = s_idx
                sub["start_time"] = normalize_tc(sub.get("start_time", ""))
                sub["end_time"] = normalize_tc(sub.get("end_time", ""))

            total_lines = len(fixed_subtitles)
            flagged_lines = sum(1 for s in fixed_subtitles if s.get("flagged"))

            try:
                log_job(filename, file_ext, platform, structure, total_lines, flagged_lines, 0)
            except Exception as e:
                print(f"Failed to log job: {e}")

            final_result = {
                "subtitles": fixed_subtitles,
                "stats": {
                    "total_lines": total_lines,
                    "flagged_lines": flagged_lines,
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
    platform: str = Form(default="discovery_max")
):
    ALLOWED = [".doc",".docx",".pdf",".xml",".ttml",".dfxp",
               ".rtf",".srt",".vtt",".webvtt",".xlsx",".xls",
               ".csv",".txt",".json"]

    filename = file.filename or "unknown.txt"
    ext = "." + filename.lower().rsplit(".", 1)[-1] if "." in filename else ""

    if ext not in ALLOWED:
        raise HTTPException(400, f"File type '{ext}' not supported.")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(400, "Uploaded file is empty")

    file_data = read_file(file_bytes, filename)
    raw_text = file_data["raw_text"]
    structure = file_data["structure"]

    if not raw_text.strip():
        raise HTTPException(400, "Could not extract text from file")

    platform_dict = get_platform(platform)
    timecoded_subtitles = parse_timecoded_subtitles(raw_text)
    if timecoded_subtitles:
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

    pre_extracted = pre_extract_dialogue(raw_text, structure, file_bytes, filename, platform_dict)
    if not pre_extracted:
        pre_extracted = raw_text.splitlines()

    subtitles = []
    for i, line in enumerate(pre_extracted, 1):
        clean_line = line.strip()
        if clean_line:
            subtitles.append({"id": i, "text": clean_line, "flagged": False})

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
    result["subtitles"] = subtitles

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
    guidelines_file: UploadFile = File(None),
    guidelines_text: str = Form(default="")
):
    if not platform_name.strip():
        raise HTTPException(400, "Platform name is required")

    platform_key = "custom_" + re.sub(r'[^a-z0-9]', '_', platform_name.lower().strip())

    raw_guidelines = ""
    if guidelines_file and guidelines_file.filename:
        file_bytes = await guidelines_file.read()
        file_data = read_file(file_bytes, guidelines_file.filename)
        raw_guidelines = file_data["raw_text"]
    elif guidelines_text.strip():
        raw_guidelines = guidelines_text.strip()

    if raw_guidelines:
        platform_data = extract_platform_rules_with_ai(raw_guidelines, platform_name.strip())
    else:
        platform_data = {
            "name": platform_name.strip(),
            "max_chars_per_line": 42,
            "max_lines": 2,
            "rules": ["Maximum 42 characters per line", "Maximum 2 lines", "Standard guidelines"],
            "summary": f"Custom: {platform_name.strip()}"
        }

    platform_data["guidelines_raw"] = raw_guidelines
    save_custom_platform(platform_key, platform_data)

    return {
        "success": True,
        "platform_key": platform_key,
        "platform_name": platform_name.strip(),
        "rules_extracted": len(platform_data.get("rules", [])),
        "message": f"Platform '{platform_name}' added with {len(platform_data.get('rules', []))} rules"
    }


@app.delete("/platforms/{platform_key}")
def delete_platform(platform_key: str):
    if not platform_key.startswith("custom_"):
        raise HTTPException(400, "Cannot delete built-in platforms")
    from database import get_connection
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM platforms WHERE platform_key=%s AND is_custom=TRUE", (platform_key,))
    affected = cursor.rowcount
    conn.commit()
    cursor.close()
    conn.close()
    if affected == 0:
        raise HTTPException(404, "Platform not found")
    return {"success": True}


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
