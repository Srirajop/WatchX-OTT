import re

from platform_rules import get_platform


_ARROW = re.compile(r"\s*-->\s*")
_SRT_TC = re.compile(r"^\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}$")
_FRAME_TC = re.compile(r"^\d{1,2}:\d{2}:\d{2}[:;]\d{1,2}$")
_INLINE_RANGE = re.compile(
    r"(?P<start>\d{1,2}:\d{2}:\d{2}[,.:;]\d{1,3})\s*-->\s*"
    r"(?P<end>\d{1,2}:\d{2}:\d{2}[,.:;]\d{1,3})"
)
_LEADING_TIMECODE = re.compile(r"^(?P<start>\d{1,2}:\d{2}:\d{2}[,.:;]\d{1,3})(?P<rest>.*)$")
_FPS = 25


def normalize_timecode(value: str) -> str:
    """Normalize common subtitle timecodes to SRT HH:MM:SS,mmm."""
    if not value:
        return ""

    tc = value.strip()
    tc = re.split(r"\s+", tc, maxsplit=1)[0]

    if _SRT_TC.match(tc):
        h, m, rest = tc.replace(".", ",").split(":")
        s, ms = rest.split(",")
        return f"{int(h):02d}:{m}:{s},{ms[:3].ljust(3, '0')}"

    if _FRAME_TC.match(tc):
        h, m, s, frames = re.split(r"[:;]", tc)
        ms = round(int(frames) * 1000 / 25)
        return f"{int(h):02d}:{m}:{s},{ms:03d}"

    basic = re.match(r"^(\d{1,2}):(\d{2}):(\d{2})$", tc)
    if basic:
        h, m, s = basic.groups()
        return f"{int(h):02d}:{m}:{s},000"

    return tc


def parse_timecoded_subtitles(text: str) -> list[dict]:
    """
    Extract real timecoded subtitle entries from SRT/VTT/TTML-style text.
    This never invents timings; entries without a detectable range are skipped.
    """
    entries = []

    # Block parser for native SRT/VTT content.
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        if lines[0].isdigit():
            lines = lines[1:]
        if lines and lines[0].upper().startswith("WEBVTT"):
            lines = lines[1:]
        if not lines:
            continue

        # Check if this block actually contains multiple timing lines
        arrow_count = sum(1 for line in lines if "-->" in line)
        if arrow_count > 1:
            entries = []
            break

        timing_idx = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing_idx is not None:
            timing = _ARROW.split(lines[timing_idx], maxsplit=1)
            if len(timing) == 2:
                text_lines = lines[timing_idx + 1:]
                if text_lines:
                    entries.append(_entry(timing[0], timing[1], "\n".join(text_lines)))

    if entries:
        return _renumber(entries)

    # Line parser for normalized reader output: "start --> end | text".
    for raw_line in text.splitlines():
        line = raw_line.strip()
        match = _INLINE_RANGE.search(line)
        if not match:
            continue
        dialogue = line[match.end():].strip()
        dialogue = re.sub(r"^\|", "", dialogue).strip()
        if dialogue:
            entries.append(_entry(match.group("start"), match.group("end"), dialogue))

    if entries:
        return _renumber(entries)

    # Table/script parser for rows like:
    # 01:00:34:15 | OLIVIA (VO) | Help! Somebody, please.
    timed_rows = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.upper().startswith("TIMECODE"):
            continue

        match = _LEADING_TIMECODE.match(line)
        if not match:
            continue

        start = normalize_timecode(match.group("start"))
        rest = match.group("rest").strip()
        if rest.startswith("|"):
            rest = rest[1:].strip()

        parts = [part.strip() for part in rest.split("|") if part.strip()]
        if len(parts) >= 2:
            if _is_metadata_label(parts[-2]):
                continue
            dialogue = parts[-1]
        elif parts:
            dialogue = parts[0]
        else:
            continue

        dialogue = _strip_speaker_label(dialogue)
        dialogue = _clean_text(dialogue)
        if dialogue:
            timed_rows.append({"start_time": start, "text": dialogue})

    return _entries_from_start_times(timed_rows)


def subtitles_to_srt(subtitles: list[dict]) -> str:
    subtitles = ensure_srt_timings(subtitles)
    blocks = []
    for i, sub in enumerate(subtitles, start=1):
        text = (sub.get("text") or "").strip()
        if not text:
            continue
        start = normalize_timecode(sub.get("start_time", ""))
        end = normalize_timecode(sub.get("end_time", ""))
        if not start or not end:
            continue
        blocks.append(f"{i}\n{start} --> {end}\n{text}")
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def prepare_for_platform(subtitles: list[dict], platform_key: str, filename: str = "") -> list[dict]:
    """Apply deterministic platform delivery rules that do not require rewriting timings by AI."""
    platform = get_platform(platform_key)
    min_duration = float(platform.get("min_duration_seconds", 1.0))
    max_duration = float(platform.get("max_duration_seconds", 7.0))
    min_gap = float(platform.get("min_interval_seconds", 0.02))
    max_cps = float(platform.get("reading_speed_max_cps", 21))
    max_chars = int(platform.get("max_chars_per_line", 42))
    max_lines = int(platform.get("max_lines", 2))

    cleaned = []
    for sub in ensure_srt_timings(subtitles):
        text = clean_delivery_text(sub.get("text", ""))
        if not _is_dialogue_text(text):
            continue
        item = dict(sub)
        item["text"] = text
        cleaned.append(item)

    cleaned.sort(key=lambda item: _to_seconds(item.get("start_time", "")) or 0)
    cleaned = _split_long_subtitles(cleaned, max_chars, max_lines)
    cleaned = _repair_timing_windows(cleaned, min_duration, max_duration, min_gap, max_cps)

    if platform.get("zero_subtitle_required", False):
        cleaned = _ensure_zero_subtitle(cleaned, min_duration, filename)

    for idx, sub in enumerate(cleaned, start=1):
        sub["id"] = idx
        sub.setdefault("flagged", False)
        sub.setdefault("flag_reason", "")

    return cleaned


# Speaker name pattern: ALL-CAPS word(s) 1-4 words long with NO lowercase following on same token
_INLINE_SPEAKER = re.compile(
    r"^([A-Z]{2,30}(?:\s+[A-Z0-9]{1,30}){0,3}|[A-Z]\s+[A-Z0-9]{1,30})\s+(?=[A-Z][a-z]|I\s|['\"\(]|\d)"
)

# Production/metadata noise that should never appear as a subtitle
_METADATA_LINE = re.compile(
    r'^(ACT\s+(ONE|TWO|THREE|FOUR|FIVE|\d+)'  # ACT ONE, ACT 1
    r'|SCENE\s+\d+'                             # SCENE 1
    r'|TEASER|COLD\s+OPEN|TAG'                 # structural labels
    r'|FADE\s+IN|FADE\s+OUT|CUT\s+TO'          # edit directions
    r'|SMASH\s+CUT|MATCH\s+CUT'               # edit directions
    r'|END\s+(OF\s+)?EPISODE'                  # END OF EPISODE / END EPISODE
    r'|MAIN\s+TITLE'                           # MAIN TITLE EVIL etc
    r'|END\s+CREDITS|OPENING\s+CREDITS'       # credit labels
    r'|TITLE\s+SEQUENCE'                       # title sequence
    r'|INT\.|EXT\.|INT/EXT\.|EXT/INT\.'       # scene headings
    r'|(\d+(ST|ND|RD|TH)\s+QC:)'             # QC notes like "1st QC: Jared M."
    r')',
    re.IGNORECASE
)


def clean_delivery_text(text: str) -> str:
    # Remove all parenthesized and bracketed content first (handles multiline)
    text = re.sub(r"\([^)]+\)", "", text, flags=re.DOTALL)
    text = re.sub(r"\[[^\]]+\]", "", text, flags=re.DOTALL)
    # Remove HTML/markup tags
    text = re.sub(r"<[^>]+>", "", text)

    # Split text into lines
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    cleaned_lines = []

    for line in lines:
        # Skip page number references
        if re.match(r"^Page\s+\d+$", line, re.IGNORECASE):
            continue

        # Skip any production metadata / scene headings
        if _METADATA_LINE.match(line):
            continue

        # Skip any line containing a scene heading keyword anywhere
        if re.search(r'\b(INT\.|EXT\.|INT/EXT\.|EXT/INT\.)', line, re.IGNORECASE):
            continue

        # Skip on-screen text / burn-in labels
        if re.match(
            r"^(ON-SCREEN|ON\s+SCREEN|ON\s+SIGN|TEXT\s+ON|TRAUMA\s+CENTER|EMERGENCY|Admitting|Outpatient|Registration)",
            line, re.IGNORECASE
        ):
            continue

        # Skip QC / production note lines at the end of files
        if re.search(r'\d+(st|nd|rd|th)\s+QC\s*:', line, re.IGNORECASE):
            continue

        # Skip pure speaker-name lines (all uppercase, no sentence punctuation)
        stripped_for_check = re.sub(r"[\s.'\-/&#,/()+]+", "", line)
        if stripped_for_check.isupper() and len(stripped_for_check) > 0 and len(stripped_for_check) <= 40:
            if not re.search(r"[!?]", line) and not re.search(r'[a-z]', line):
                continue  # pure speaker label — drop it

        # Strip speaker prefix WITH colon or dash separator (e.g. "DAVID: Hello" / "DAVID - Hello")
        line = re.sub(r"^[A-Z][A-Z0-9 .'\-/()#&,]{0,60}[:\-]\s*", "", line)

        # Strip speaker prefix WITHOUT colon/dash — ALL-CAPS word(s) followed by mixed-case dialogue
        # e.g. "LILA I thought he seemed sad." → "I thought he seemed sad."
        m = _INLINE_SPEAKER.match(line)
        if m:
            line = line[m.end():].strip()

        line = re.sub(r"\s+", " ", line).strip()
        if line:
            cleaned_lines.append(line)

    return "\n".join(cleaned_lines).strip()


def ensure_srt_timings(subtitles: list[dict]) -> list[dict]:
    """Fill missing end times from the next start time when possible."""
    normalized = []
    for sub in subtitles:
        item = dict(sub)
        item["start_time"] = normalize_timecode(item.get("start_time", ""))
        item["end_time"] = normalize_timecode(item.get("end_time", ""))
        normalized.append(item)

    for i, item in enumerate(normalized):
        if item.get("start_time") and not item.get("end_time"):
            start_sec = _to_seconds(item["start_time"])
            if start_sec is None:
                continue
            next_start_sec = None
            for later in normalized[i + 1:]:
                ls = _to_seconds(later.get("start_time", ""))
                if ls is not None and ls > start_sec:
                    next_start_sec = ls
                    break
            
            if next_start_sec:
                # End 2 frames before the next subtitle
                item["end_time"] = _from_seconds(max(start_sec + 2/25, next_start_sec - 2/25))
            else:
                item["end_time"] = _add_seconds(item["start_time"], 2)

    return normalized


def _repair_timing_windows(subtitles: list[dict], min_duration: float, max_duration: float, min_gap: float, max_cps: float) -> list[dict]:
    repaired = []
    fps = 25
    min_gap_frames = max(1, round(min_gap * fps))
    last_end_time = -1.0
    
    for i, sub in enumerate(subtitles):
        item = dict(sub)
        start = _to_seconds(item.get("start_time", ""))
        end = _to_seconds(item.get("end_time", ""))
        if start is None:
            continue

        # 1. Enforce minimum gap from previous subtitle (Ripple effect)
        if last_end_time >= 0:
            min_allowed_start = last_end_time + (min_gap_frames / fps)
            if start < min_allowed_start:
                start = min_allowed_start

        if end is None or end <= start:
            end = start + min_duration

        # 2. Enforce max CPS and min duration
        chars = len(re.sub(r"\s", "", re.sub(r"<[^>]+>", "", item.get("text", ""))))
        cps_duration = chars / max_cps if max_cps > 0 else min_duration
        required_duration = max(min_duration, cps_duration)

        if end - start < required_duration:
            end = start + required_duration

        # 3. Enforce max duration cap
        if end - start > max_duration:
            end = start + max_duration

        # 4. Final safety check & Grid Snap
        if end <= start:
            end = start + (1 / fps)

        start = round(start * fps) / fps
        end = round(end * fps) / fps

        item["start_time"] = _from_seconds(start)
        item["end_time"] = _from_seconds(end)
        repaired.append(item)
        
        last_end_time = end

    return repaired


def _split_long_subtitles(subtitles: list[dict], max_chars: int, max_lines: int) -> list[dict]:
    split = []
    for sub in subtitles:
        text = sub.get("text", "")
        if _text_fits(text, max_chars, max_lines):
            item = dict(sub)
            item["text"] = _wrap_chunk(text, max_chars)
            split.append(item)
            continue

        chunks = _chunk_wrapped_groups(text, max_chars, max_lines)
        if len(chunks) <= 1:
            item = dict(sub)
            item["text"] = _wrap_chunk(text, max_chars)
            split.append(item)
            continue

        start = _to_seconds(sub.get("start_time", ""))
        end = _to_seconds(sub.get("end_time", ""))
        if start is None or end is None or end <= start:
            for chunk in chunks:
                item = dict(sub)
                item["text"] = _wrap_chunk(chunk, max_chars)
                split.append(item)
            continue

        duration = end - start
        weights = [max(1, len(re.sub(r"\s+", "", chunk))) for chunk in chunks]
        total = sum(weights)
        cursor = start
        for idx, chunk in enumerate(chunks):
            item = dict(sub)
            if idx == len(chunks) - 1:
                chunk_end = end
            else:
                chunk_end = cursor + duration * (weights[idx] / total)
            item["start_time"] = _from_seconds(cursor)
            item["end_time"] = _from_seconds(chunk_end)
            item["text"] = chunk
            split.append(item)
            cursor = chunk_end

    return split


def _text_fits(text: str, max_chars: int, max_lines: int) -> bool:
    lines = _wrap_chunk(text, max_chars).splitlines()
    return len(lines) <= max_lines and all(len(line) <= max_chars for line in lines)


def _chunk_wrapped_groups(text: str, max_chars: int, max_lines: int) -> list[str]:
    lines = _wrap_chunk(text, max_chars).splitlines()
    return ["\n".join(lines[i:i + max_lines]) for i in range(0, len(lines), max_lines)]


def _wrap_chunk(text: str, max_chars: int) -> str:
    words = text.split()
    lines = []
    current = []
    for word in words:
        proposed = " ".join(current + [word])
        if current and len(proposed) > max_chars:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return "\n".join(lines)


def _ensure_zero_subtitle(subtitles: list[dict], min_duration: float, filename: str) -> list[dict]:
    if subtitles and _looks_like_zero_subtitle(subtitles[0].get("text", "")):
        return subtitles

    show_name = _show_name_from_filename(filename)
    zero = {
        "id": 1,
        "start_time": "00:00:00,000",
        "end_time": _from_seconds(max(min_duration, 1.08)),
        "text": f"{show_name}\nSTORY: UNKNOWN\nLANG: ENG",
        "flagged": False,
        "flag_reason": "",
    }
    return [zero] + subtitles


def _looks_like_zero_subtitle(text: str) -> bool:
    upper = (text or "").upper()
    return "STORY:" in upper and "LANG:" in upper


def _show_name_from_filename(filename: str) -> str:
    name = (filename or "PROGRAM").rsplit(".", 1)[0]
    name = re.sub(r"[_\-]+", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name.upper() or "PROGRAM"


def _entry(start: str, end: str, text: str) -> dict:
    start_tc = normalize_timecode(start)
    end_tc = normalize_timecode(end)
    
    start_sec = _to_seconds(start_tc)
    end_sec = _to_seconds(end_tc)
    
    if start_sec is not None and end_sec is not None:
        if end_sec <= start_sec:
            end_tc = _add_seconds(start_tc, 1.0)
            
    return {
        "id": 0,
        "start_time": start_tc,
        "end_time": end_tc,
        "text": _clean_text(text),
        "flagged": False,
        "flag_reason": "",
    }


def _clean_text(text: str) -> str:
    cleaned = clean_delivery_text(text)
    cleaned = re.sub(r"{\\.*?}", "", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    return "\n".join(line.strip() for line in cleaned.splitlines() if line.strip()).strip()


def _strip_speaker_label(text: str) -> str:
    return re.sub(r"^[A-Z][A-Z0-9 .'\-/()#&,]{1,60}[:\-]\s*", "", text).strip()


def _is_metadata_label(text: str) -> bool:
    return bool(re.search(
        r"^(NARRATIVE TITLE|GRAPHICS ON SCREEN|MUSIC|WALLA|LOGO|TITLE CARD|ON SCREEN|CAPTION|INSERT)$",
        text.strip(),
        re.IGNORECASE,
    ))


def _is_dialogue_text(text: str) -> bool:
    if not text or len(text.strip()) < 2:
        return False
    cleaned = text.strip()
    if _looks_like_zero_subtitle(cleaned):
        return True
    # Filter out all production metadata lines
    if _METADATA_LINE.match(cleaned):
        return False
    if re.match(r"^(FADE IN|FADE OUT|CUT TO|SMASH CUT|END CREDITS|OPENING CREDITS|TITLE SEQUENCE)$", cleaned, re.IGNORECASE):
        return False
    if _is_metadata_label(cleaned):
        return False
    # Filter pure numeric/timecode lines
    if re.match(r"^[\d\s:;,.|/-]+$", cleaned):
        return False
    # Filter scene headings anywhere in line
    if re.search(r'\b(INT\.|EXT\.|INT/EXT\.|EXT/INT\.)', cleaned, re.IGNORECASE):
        return False
    # Filter QC credit lines
    if re.search(r'\d+(st|nd|rd|th)\s+QC\s*:', cleaned, re.IGNORECASE):
        return False
    return bool(re.search(r"[A-Za-z]", cleaned))


def _entries_from_start_times(rows: list[dict]) -> list[dict]:
    entries = []
    for i, row in enumerate(rows):
        start = row.get("start_time", "")
        if not start:
            continue
        next_start = rows[i + 1]["start_time"] if i + 1 < len(rows) else ""
        end = _end_before(next_start) if next_start else _add_seconds(start, 2)
        entries.append(_entry(start, end, row.get("text", "")))
    return _renumber(entries)


def _end_before(tc: str) -> str:
    seconds = _to_seconds(tc)
    if seconds is None:
        return ""
    return _from_seconds(max(0, seconds - (2 / _FPS)))


def _add_seconds(tc: str, amount: float) -> str:
    seconds = _to_seconds(tc)
    if seconds is None:
        return ""
    return _from_seconds(seconds + amount)


def _to_seconds(tc: str) -> float | None:
    tc = normalize_timecode(tc)
    match = re.match(r"^(\d{2}):(\d{2}):(\d{2}),(\d{3})$", tc)
    if not match:
        return None
    h, m, s, ms = match.groups()
    raw_seconds = int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000
    # Snap to nearest 25 FPS frame exactly
    return round(raw_seconds * _FPS) / _FPS


def _from_seconds(seconds: float) -> str:
    frames_total = round(seconds * _FPS)
    s, f = divmod(frames_total, _FPS)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    ms = round((f / _FPS) * 1000)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(ms):03d}"


def _renumber(entries: list[dict]) -> list[dict]:
    result = []
    for i, entry in enumerate(entries, start=1):
        if entry.get("text") and entry.get("start_time") and entry.get("end_time"):
            item = dict(entry)
            item["id"] = i
            result.append(item)
    return result
