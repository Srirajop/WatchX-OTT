import re

from platform_rules import get_platform


_ARROW = re.compile(r"\s*-->\s*")
_SRT_TC = re.compile(r"^\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}$")
_FRAME_TC = re.compile(r"^\d{1,2}:\d{2}:\d{2}[:;]\d{1,2}$")
# Permissive frame TC: allows single-digit MM/SS (e.g. 1:1:48:5)
_FRAME_TC_LOOSE = re.compile(r"^(\d{1,2}):(\d{1,2}):(\d{1,2})[:;](\d{1,2})$")
_INLINE_RANGE = re.compile(
    r"(?P<start>\d{1,2}[:.]\d{2}[:.]\d{2}[,.:;]?\d{0,3})\s*-->\s*"
    r"(?P<end>\d{1,2}[:.]\d{2}[:.]\d{2}[,.:;]?\d{0,3})"
)
_LEADING_TIMECODE = re.compile(r"^(?P<start>\d{1,2}[:.]\d{2}[:.]\d{2}[,.:;]?\d{0,3})(?P<rest>.*)$")
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
        return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{ms[:3].ljust(3, '0')}"

    if _FRAME_TC.match(tc):
        h, m, s, frames = re.split(r"[:;]", tc)
        ms = round(int(frames) * 1000 / 25)
        return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{ms:03d}"

    # Permissive frame TC: handles single-digit MM/SS (e.g. 1:1:48:5)
    lm = _FRAME_TC_LOOSE.match(tc)
    if lm:
        h, m, s, frames = lm.groups()
        ms = round(int(frames) * 1000 / 25)
        return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{ms:03d}"

    # Handle HH.MM.SS.FF or HH.MM.SS format (dot-separated)
    if re.match(r"^\d{1,2}\.\d{1,2}\.\d{1,2}$", tc):
        parts = tc.split(".")
        h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
        return f"{h:02d}:{m:02d}:{s:02d},000"
    elif re.match(r"^\d{1,2}\.\d{1,2}\.\d{1,2}[,.:;]\d{1,3}$", tc):
        parts = re.split(r"[,.:;]", tc)
        h, m, s, frames_or_ms = int(parts[0]), int(parts[1]), int(parts[2]), parts[3]
        if len(frames_or_ms) <= 2:  # likely frames
            ms = round(int(frames_or_ms) * 1000 / 25)
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
        else:
            return f"{h:02d}:{m:02d}:{s:02d},{frames_or_ms[:3].ljust(3, '0')}"

    basic = re.match(r"^(\d{1,2}):(\d{1,2}):(\d{1,2})$", tc)
    if basic:
        h, m, s = basic.groups()
        return f"{int(h):02d}:{int(m):02d}:{int(s):02d},000"

    return tc


def parse_timecoded_subtitles(text: str) -> list[dict]:
    """
    Extract real timecoded subtitle entries from SRT/VTT/TTML-style text.
    This never invents timings; entries without a detectable range are skipped.
    """
    # Fix broken PyPDF2 timecodes with spurious spaces: "01:01:23:1 1" -> "01:01:23:11"
    text = re.sub(r'(\d{1,2}[:.]\d{2}[:.]\d{2}[:.,;]\d)\s+(\d)\b', r'\1\2', text)
    
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

    # ── CCSL Spotting List / Column-based table parser ────────────────────
    # Handles output from _read_pdf_spatial() which produces rows like:
    #   Sh# | ShTimeIn | SceneDescription | Title | TimeIn | TimeOut | Dur | Titles
    #   19  | 01:01:47:20 | FS - THE STREET | 6 | 01:01:48:05 | 01:01:50:01 | 01:20 | REPORTER (OS): The energy crisis is real.
    # Also handles other pipe-delimited table formats from DOCX/XLSX spotting lists.
    _ANY_TC = re.compile(r"^\d{1,2}[:.]\d{2}[:.]\d{2}(?:[,.:;]\d{1,3})?$")

    # Try to detect CCSL header row and build column index map
    ccsl_col_map = {}
    ccsl_entries_found = []
    _HAS_PIPE = any('|' in l for l in text.splitlines() if not l.startswith('==='))

    if _HAS_PIPE:
        header_idx = -1
        all_lines_list = [l.strip() for l in text.splitlines()]
        for li, line in enumerate(all_lines_list):
            if re.search(r'(TimeIn|Time\s*In|TimeOut|Time\s*Out|Titles?)\b', line, re.IGNORECASE) and '|' in line:
                cells_h = [c.strip() for c in line.split('|')]
                for ci, ch in enumerate(cells_h):
                    ch_lower = ch.lower().replace(' ', '')
                    if ch_lower in ('timein', 'timein(hh:mm:ss:ff)'):
                        ccsl_col_map['start'] = ci
                    elif ch_lower in ('timeout', 'timeout(hh:mm:ss:ff)'):
                        ccsl_col_map['end'] = ci
                    elif ch_lower in ('titles', 'title', 'subtitle', 'subtitles', 'dialogue'):
                        ccsl_col_map['dialogue'] = ci
                    elif ch_lower in ('dur', 'duration'):
                        ccsl_col_map['dur'] = ci
                header_idx = li
                break

        # If we found a valid CCSL header, parse data rows
        if 'start' in ccsl_col_map and 'end' in ccsl_col_map and 'dialogue' in ccsl_col_map:
            for line in all_lines_list[header_idx + 1:]:
                if not line or line.startswith('===') or '|' not in line:
                    continue
                cells = [c.strip() for c in line.split('|')]
                if len(cells) <= max(ccsl_col_map['start'], ccsl_col_map['end'], ccsl_col_map['dialogue']):
                    continue
                start_raw = cells[ccsl_col_map['start']]
                end_raw = cells[ccsl_col_map['end']]
                dialogue_raw = cells[ccsl_col_map['dialogue']]

                # Skip empty or non-timecode rows
                if not _ANY_TC.match(start_raw.strip()) or not _ANY_TC.match(end_raw.strip()):
                    continue
                if not dialogue_raw.strip():
                    continue

                # Convert **text** bold markers to <b>text</b>
                dialogue_raw = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', dialogue_raw)
                # Convert *text* italic markers to <i>text</i>
                dialogue_raw = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', dialogue_raw)

                start_tc = normalize_timecode(start_raw.strip())
                end_tc = normalize_timecode(end_raw.strip())
                dialogue_text = _strip_speaker_label(dialogue_raw.strip())
                dialogue_text = _clean_text(dialogue_text)
                if dialogue_text:
                    ccsl_entries_found.append(_entry(start_tc, end_tc, dialogue_text))

        if ccsl_entries_found:
            return _renumber(ccsl_entries_found)

    # Table/script parser for rows like:
    # 01:00:34:15 | OLIVIA (VO) | Help! Somebody, please.
    # Or Spotting Lists: 00.08.00 INT./EXT. | 4-1 | WES (TO SYDNEY)- Be careful. | 00.08.02 | 00.08.18 | 0.16
    timed_rows = []
    _ANY_TC = re.compile(r"^\d{1,2}[:.]\d{2}[:.]\d{2}(?:[,.:;]\d{1,3})?$")
    
    _STRICT_TC = re.compile(r'\b\d{1,2}[:.]\d{2}[:.]\d{2}(?:[,.:;]\d{1,3})?\b')
    
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.upper().startswith("TIMECODE") or line.startswith("==="):
            continue

        # If line doesn't have | but has multiple timecodes, convert space-delimited timecodes to |
        if "|" not in line and len(_STRICT_TC.findall(line)) >= 2:
            line = _STRICT_TC.sub(r' | \g<0> | ', line)
            line = re.sub(r'\|\s*\|', '|', line)
            line = re.sub(r'\s+', ' ', line).strip(' |')

        cells = [c.strip() for c in line.split("|")]
        
        # Check if the row contains valid timecodes, especially at the end
        dialogue = ""
        tc_matches = []
        for i in range(len(cells)-1, -1, -1):
            if _ANY_TC.match(cells[i]):
                tc_matches.append(cells[i])
            else:
                if not dialogue and cells[i] and not re.match(r'^[\d\.]+$', cells[i]):
                    dialogue = cells[i]
                    
        if len(tc_matches) >= 2:
            start = normalize_timecode(tc_matches[1])
            end = normalize_timecode(tc_matches[0])
            
            # Remove any leading duration like "02:12 " before extracting dialogue
            dialogue = re.sub(r'^\d{1,2}[:.;]\d{2}\s+', '', dialogue)
            
            dialogue = _strip_speaker_label(dialogue)
            dialogue = _clean_text(dialogue)
            if dialogue:
                entries.append(_entry(start, end, dialogue))
            continue
            
        # Continuation line check: if no timecodes but we have cells, append to previous entry
        if not tc_matches and entries and len(cells) > 0:
            potential_text = cells[-1]
            if potential_text and not re.match(r'^[\d\.]+$', potential_text) and not _is_metadata_label(potential_text):
                cleaned_extra = _strip_speaker_label(potential_text)
                cleaned_extra = _clean_text(cleaned_extra)
                if cleaned_extra:
                    entries[-1]["text"] += "\n" + cleaned_extra
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

    if timed_rows:
        entries.extend(_entries_from_start_times(timed_rows))

    if entries:
        return _renumber(entries)
    
    return []


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
    r'|INT\.|EXT\.|INT/EXT\.|EXT/INT\.'       # scene headings
    r'|(\d+(ST|ND|RD|TH)\s+QC:)'             # QC notes like "1st QC: Jared M."
    r')',
    re.IGNORECASE
)


def clean_delivery_text(text: str) -> str:
    """
    Clean dialogue text for OTT delivery.
    IMPORTANT: Preserves <i> and <b> italic/bold tags — these carry platform
    formatting (songs, narration, VO) that MUST be kept intact.
    Only strips stage-direction parenthetical content, not all brackets.
    """
    # ── 1. Stash any <i>/<b> tags so we can restore them after cleaning ──
    # We replace them with unique placeholders, clean, then put them back.
    text = re.sub(r'<i>', '__ITALIC_OPEN__', text)
    text = re.sub(r'</i>', '__ITALIC_CLOSE__', text)
    text = re.sub(r'<b>', '__BOLD_OPEN__', text)
    text = re.sub(r'</b>', '__BOLD_CLOSE__', text)

    # ── 2. Remove ONLY stage-direction parentheticals (not all brackets) ──
    # Keep: (VO), (OS), (CONT'D), (singing), (screaming) when they are alone
    # Remove: (speaking Spanish), (to himself), (through phone), etc.
    _STAGE_PARENS = re.compile(
        r'\((speaking\s+\w+|through\s+\w+|into\s+\w+|to\s+[^)]+|whispering[^)]*'
        r'|overlaps?|Archive|continues?[^)]*|indistinct[^)]*|.*?music.*?'
        r'|sarcastically|quietly|loudly|angrily|softly|nervously|in\s+\w+'
        r'|LAUGHS?|CHUCKLES?|GASPS?|SIGHS?|SCREAMS?|CRIES?|SOBBING|MOANS?|GROANS?'
        r'|from\s+[^)]+|off\s*camera|off\s*screen)\)',
        re.IGNORECASE
    )
    text = _STAGE_PARENS.sub('', text)

    # Remove sound-effect brackets [MUSIC], [APPLAUSE] but NOT [words in song]
    text = re.sub(r'\[(?:MUSIC|APPLAUSE|LAUGHTER|CHEERING|GUNSHOT|EXPLOSION|SINGING)[^\]]*\]', '', text, flags=re.IGNORECASE)

    # ── 3. Remove truly spurious HTML tags but NOT i/b placeholders ──
    text = re.sub(r'<(?!/?i>|/?b>)[^>]+>', '', text)

    # ── 4. Restore italic/bold tags ──
    text = text.replace('__ITALIC_OPEN__', '<i>')
    text = text.replace('__ITALIC_CLOSE__', '</i>')
    text = text.replace('__BOLD_OPEN__', '<b>')
    text = text.replace('__BOLD_CLOSE__', '</b>')

    # Split text into lines for per-line processing
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

        # Keep on-screen text / burn-in labels but strip purely administrative ones if needed.
        # Removed dropping ON-SCREEN/ON SIGN so they can act as forced narratives.
        if re.match(
            r"^(TRAUMA\s+CENTER|EMERGENCY|Admitting|Outpatient|Registration)$",
            line, re.IGNORECASE
        ):
            continue

        # Skip QC / production note lines at the end of files
        if re.search(r'\d+(st|nd|rd|th)\s+QC\s*:', line, re.IGNORECASE):
            continue

        # Skip pure speaker-name lines (all uppercase, no sentence punctuation)
        # BUT never skip lines that contain music notes (♪ ♫) — those are song lyrics
        stripped_for_check = re.sub(r"[\s.'\-/&#,/()+<>]+", "", re.sub(r'<[^>]+>', '', line))
        has_music = bool(re.search(r'[♪♫🎵🎶]', line))
        if not has_music and stripped_for_check.isupper() and 0 < len(stripped_for_check) <= 40:
            if not re.search(r"[!?]", line) and not re.search(r'[a-z]', line):
                continue  # pure speaker label — drop it

        # Strip speaker prefix WITH colon or dash separator (e.g. "DAVID: Hello" / "DAVID - Hello")
        # Only strip if the RESULT is not empty
        stripped_speaker = re.sub(r"^[A-Z][A-Z0-9 .'\-/()#&,]{0,60}[:\-]\s*", "", line)
        if stripped_speaker.strip():   # don't blank out the whole line
            line = stripped_speaker

        # Strip speaker prefix WITHOUT colon/dash — ALL-CAPS word(s) followed by mixed-case dialogue
        # e.g. "LILA I thought he seemed sad." → "I thought he seemed sad."
        m = _INLINE_SPEAKER.match(line)
        if m and line[m.end():].strip():
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
    """Clean entry text — preserves <i>/<b> tags for OTT italic/bold formatting."""
    cleaned = clean_delivery_text(text)
    # Remove RTF control sequences but NOT HTML italic/bold tags
    cleaned = re.sub(r"\{\\[^}]+\}", "", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    return "\n".join(line.strip() for line in cleaned.splitlines() if line.strip()).strip()


def _strip_speaker_label(text: str) -> str:
    return re.sub(r"^[A-Z][A-Z0-9 .'\-/()#&,]{1,60}[:\-]\s*", "", text).strip()


def _is_metadata_label(text: str) -> bool:
    return bool(re.search(
        r"^(MUSIC|WALLA)$",
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
    if re.match(r"^(FADE IN|FADE OUT|CUT TO|SMASH CUT)$", cleaned, re.IGNORECASE):
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
