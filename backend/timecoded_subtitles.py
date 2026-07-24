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


def _format_hms_ms(h: int, m: int, s: int, ms: int) -> str:
    if ms >= 1000:
        extra_s, ms = divmod(ms, 1000)
        s += extra_s
    if s >= 60:
        extra_m, s = divmod(s, 60)
        m += extra_m
    if m >= 60:
        extra_h, m = divmod(m, 60)
        h += extra_h
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def normalize_timecode(value: str) -> str:
    """Normalize common subtitle timecodes to SRT HH:MM:SS,mmm."""
    if not value:
        return ""

    tc = value.strip()
    tc = re.split(r"\s+", tc, maxsplit=1)[0]

    if _SRT_TC.match(tc):
        h, m, rest = tc.replace(".", ",").split(":")
        s, ms = rest.split(",")
        return _format_hms_ms(int(h), int(m), int(s), int(ms[:3].ljust(3, '0')))

    if _FRAME_TC.match(tc):
        h, m, s, frames = re.split(r"[:;]", tc)
        ms = round(int(frames) * 1000 / 25)
        return _format_hms_ms(int(h), int(m), int(s), ms)

    # Permissive frame TC: handles single-digit MM/SS (e.g. 1:1:48:5)
    lm = _FRAME_TC_LOOSE.match(tc)
    if lm:
        h, m, s, frames = lm.groups()
        ms = round(int(frames) * 1000 / 25)
        return _format_hms_ms(int(h), int(m), int(s), ms)

    # Handle HH.MM.SS.FF or HH.MM.SS format (dot-separated)
    if re.match(r"^\d{1,2}\.\d{1,2}\.\d{1,2}$", tc):
        parts = tc.split(".")
        h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
        return _format_hms_ms(h, m, s, 0)
    elif re.match(r"^\d{1,2}\.\d{1,2}\.\d{1,2}[,.:;]\d{1,3}$", tc):
        parts = re.split(r"[,.:;]", tc)
        h, m, s, frames_or_ms = int(parts[0]), int(parts[1]), int(parts[2]), parts[3]
        if len(frames_or_ms) <= 2:  # likely frames
            ms = round(int(frames_or_ms) * 1000 / 25)
            return _format_hms_ms(h, m, s, ms)
        else:
            return _format_hms_ms(h, m, s, int(frames_or_ms[:3].ljust(3, '0')))

    basic = re.match(r"^(\d{1,2}):(\d{1,2}):(\d{1,2})$", tc)
    if basic:
        h, m, s = basic.groups()
        return _format_hms_ms(int(h), int(m), int(s), 0)

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
        if lines and lines[0].upper().startswith("WEBVTT"):
            lines = lines[1:]
        if not lines:
            continue

        cur_start, cur_end = None, None
        cur_text_lines = []

        for line in lines:
            if line.isdigit() and not cur_start:
                continue
            if "-->" in line:
                if cur_start and cur_text_lines:
                    entries.append(_entry(cur_start, cur_end, "\n".join(cur_text_lines)))
                    cur_text_lines = []
                timing = _ARROW.split(line, maxsplit=1)
                if len(timing) == 2:
                    cur_start, cur_end = timing[0].strip(), timing[1].strip()
            elif cur_start:
                cur_text_lines.append(line)

        if cur_start and cur_text_lines:
            entries.append(_entry(cur_start, cur_end, "\n".join(cur_text_lines)))

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

    # ── General Column-Based Table Parser ──────────────────────────────────
    # Handles output from _read_pdf_spatial() which produces rows like:
    #   Sh# | ShTimeIn | SceneDescription | Title | TimeIn | TimeOut | Dur | Titles
    #   19  | 01:01:47:20 | FS - THE STREET | 6 | 01:01:48:05 | 01:01:50:01 | 01:20 | REPORTER (OS): The energy crisis is real.
    # Also handles other pipe-delimited table formats from DOCX/XLSX spotting
    # lists, INCLUDING formats never seen before — this is a SEMANTIC column
    # classifier, not a fixed list of known header names. It classifies each
    # column by what kind of content it holds (a timecode column? a
    # narration/dialogue column? a visual/scene-description column that must
    # NEVER be mistaken for dialogue?) using a broad synonym set PLUS the
    # actual shape of the data in that column, so a new OTT client's table
    # with header names we've never seen — e.g. "TIME CODE | VISUALS | AUDIO"
    # — gets classified correctly without writing a new special case for it.
    _ANY_TC = re.compile(r"^\d{1,2}[:.]\d{2}[:.]\d{2}(?:[,.:;]\d{1,3})?$")

    # Synonym sets for each semantic column role. Adding support for a new
    # client's wording (e.g. "NARRATION" instead of "AUDIO") means adding one
    # word to a set below, not writing a new parser branch.
    _COL_SYNONYMS = {
        "time_single": {
            "timecode", "timecodes", "time", "tc", "timein", "time(hh:mm:ss:ff)",
        },
        "time_start": {
            "timein", "time in", "in", "shtimein", "startcode", "start",
        },
        "time_end": {
            "timeout", "time out", "out", "endcode", "end",
        },
        "duration": {
            "dur", "duration", "len", "length",
        },
        # Columns whose text IS spoken dialogue — safe to use as subtitle text.
        "dialogue": {
            "titles", "title", "subtitle", "subtitles", "dialogue", "dialog",
            "audio", "narration", "narrator", "voiceover", "vo", "speech",
            "text", "spoken", "english", "transcript", "translation",
        },
        # Columns whose text is NEVER spoken dialogue, even when the
        # dialogue/audio column is empty for that row. This is the exact
        # fix for the CAR SOS / Food Factory bug: a VISUALS or SCENE
        # DESCRIPTION column must never be picked as a fallback "dialogue"
        # just because it's the only non-empty, non-timecode cell in the row.
        "non_dialogue": {
            "visuals", "visual", "video", "scenedescription", "scene",
            "shotdescription", "shot", "graphics", "screenshot", "image",
            "notes", "comment", "comments", "sh#", "sh", "shot#",
            "actuality", "action", "onscreen", "on screen",
        },
    }

    def _classify_header_cell(cell_text: str) -> str | None:
        norm = re.sub(r'[^a-z0-9 ]', '', cell_text.lower()).strip()
        norm_nospace = norm.replace(' ', '')
        for role, synonyms in _COL_SYNONYMS.items():
            for syn in synonyms:
                syn_nospace = syn.replace(' ', '')
                if norm_nospace == syn_nospace or norm == syn:
                    return role
        return None

    # Try to detect a header row and build a semantic column index map
    col_map = {}  # role -> column index, roles: start, end, dialogue, non_dialogue(set), dur
    non_dialogue_cols = set()
    table_entries_found = []
    _HAS_PIPE = any('|' in l for l in text.splitlines() if not l.startswith('==='))

    if _HAS_PIPE:
        header_idx = -1
        all_lines_list = [l.strip() for l in text.splitlines()]
        for li, line in enumerate(all_lines_list):
            if '|' not in line:
                continue
            cells_h = [c.strip() for c in line.split('|')]
            roles_found = {}
            nd_cols_this_line = set()
            for ci, ch in enumerate(cells_h):
                role = _classify_header_cell(ch)
                if role in ("time_start", "time_single"):
                    roles_found.setdefault("start", ci)
                elif role == "time_end":
                    roles_found["end"] = ci
                elif role == "dialogue":
                    roles_found["dialogue"] = ci
                elif role == "duration":
                    roles_found["dur"] = ci
                elif role == "non_dialogue":
                    nd_cols_this_line.add(ci)

            # A usable header needs at minimum: a time column AND a dialogue
            # column. (start+end+dialogue is the richest case / CCSL-style;
            # start-only+dialogue is the simpler single-timecode case, e.g.
            # "TIME CODE | VISUALS | AUDIO" — handled by the same code path
            # now, not a separate branch.)
            if "start" in roles_found and "dialogue" in roles_found:
                col_map = roles_found
                non_dialogue_cols = nd_cols_this_line
                header_idx = li
                break

        if "start" in col_map and "dialogue" in col_map:
            has_end_col = "end" in col_map

            # Accumulate each cue's dialogue across its pipe-line AND any
            # continuation lines, then clean + flush when the next
            # timecode appears.  (Defering avoids the bug where a
            # cue whose pipe-line is only a speaker label gets
            # dropped, orphaning the rest of its dialogue.)
            def _flush_cue(cur):
                if not cur:
                    return
                start_raw = cur["start"]
                if not _ANY_TC.match(start_raw.strip()):
                    return
                end_raw = cur.get("end", "")
                has_end_this = cur.get("has_end", has_end_col)
                dialogue_raw = cur["text"].strip()
                if not dialogue_raw:
                    return
                dialogue_text = _strip_speaker_label(dialogue_raw)
                dialogue_text = _clean_text(dialogue_text)
                if not dialogue_text:
                    return
                start_tc = normalize_timecode(start_raw.strip())
                end_tc = normalize_timecode(end_raw) if has_end_this else None
                if has_end_col:
                    table_entries_found.append(_entry(start_tc, end_tc or start_tc, dialogue_text))
                else:
                    table_entries_found.append({"start_time": start_tc, "text": dialogue_text})

            cur = None
            for line in all_lines_list[header_idx + 1:]:
                if not line or line.startswith('===') or '|' not in line:
                    # Continuation of the current cue's dialogue.
                    if cur is not None:
                        cur["text"] += "\n" + line.strip()
                    continue
                cells = [c.strip() for c in line.split('|')]
                needed_idx = [col_map['start'], col_map['dialogue']] + ([col_map['end']] if has_end_col else [])
                if len(cells) <= max(needed_idx):
                    # Not a usable timecode row — treat as continuation.
                    if cur is not None:
                        cur["text"] += "\n" + line.strip()
                    continue
                # New timecode row: flush the previous cue first.
                _flush_cue(cur)
                start_raw = cells[col_map['start']]
                if not _ANY_TC.match(start_raw.strip()):
                    cur = None
                    continue
                end_raw = cells[col_map['end']].strip() if has_end_col else ""
                has_end_this = has_end_col
                if has_end_col and not _ANY_TC.match(end_raw):
                    has_end_this = False
                # Convert **text** / *text* markers now so later
                # continuation lines also keep them intact.
                dialogue_raw = cells[col_map['dialogue']].strip()
                dialogue_raw = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', dialogue_raw)
                dialogue_raw = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', dialogue_raw)
                cur = {
                    "start": start_raw,
                    "end": end_raw,
                    "has_end": has_end_this,
                    "text": dialogue_raw,
                }
            _flush_cue(cur)

        if table_entries_found:
            if "end" not in col_map:
                return _entries_from_start_times(table_entries_found)
            return _renumber(table_entries_found)

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

    # ── Flat-Column Script Parser ───────────────────────────────────────────
    # Handles PDFs like Tiny Toons (Deluxe As-Broadcast) where TIMECODE,
    # CHARACTER NAME, and DIALOGUE are on SEPARATE consecutive lines:
    #   01:00:07:06
    #   BUSTER
    #   (singing) We're tiny
    #   01:00:08:01
    #   BABS
    #   We're toony
    # The parser walks forward, identifies standalone timecode lines, skips
    # ALL-CAPS speaker-label lines & page-header noise, then accumulates
    # dialogue lines until the next timecode or page break appears.
    _STANDALONE_TC = re.compile(
        r"^\d{1,2}[:.]?\d{2}[:.]?\d{2}(?:[:.,;]\d{1,3})?\s*$"
    )
    _ALLCAPS_LABEL = re.compile(
        r"^[A-Z][A-Z0-9 .,\-'/()\[\]&]{0,60}$"
    )
    _PAGE_HEADER = re.compile(
        r"^(Page\s+\d+|=== PAGE|\d{1,3}/\d{1,3}|Prepared\s+by:|Deluxe|As-Broadcast\s+Script)",
        re.IGNORECASE
    )
    # Parenthetical content that should be skipped entirely (slang notes, translators' annotations)
    _ANNOTATION = re.compile(
        r"^\((?:[^)]{0,120}=\s*[^)]{0,120}|reference to|note\s+(?:slant|rhyme)|a fictional|blend of|short for|crazy or)\)",
        re.IGNORECASE
    )
    # Must have at least N timecodes that look frame-accurate (HH:MM:SS:FF) to
    # apply this parser — prevents false-positive on ordinary plain scripts.
    _FRAME_TC_LINE = re.compile(r"^\d{1,2}:\d{2}:\d{2}[:;]\d{1,2}\s*$")
    frame_tc_count = sum(1 for l in text.splitlines() if _FRAME_TC_LINE.match(l.strip()))

    if frame_tc_count >= 5:
        flat_rows = []
        current_tc = None
        dialogue_buf = []

        def _flush_flat():
            if current_tc and dialogue_buf:
                txt = " ".join(dialogue_buf).strip()
                txt = _clean_text(txt)
                if txt:
                    flat_rows.append({"start_time": normalize_timecode(current_tc), "text": txt})

        all_lines = text.splitlines()
        i = 0
        while i < len(all_lines):
            line = all_lines[i].strip()
            i += 1
            if not line or _PAGE_HEADER.match(line):
                continue
            if _STANDALONE_TC.match(line):
                _flush_flat()
                current_tc = line.strip()
                dialogue_buf = []
                continue
            # Skip ALL-CAPS character labels (speaker names, scene headers, etc.)
            if current_tc and _ALLCAPS_LABEL.match(line) and line.upper() == line:
                continue
            # Skip translator annotations and slang notes
            if _ANNOTATION.match(line):
                continue
            # Skip bare parentheticals that are stage directions or notes
            if re.match(r"^\([^)]{3,120}\)$", line):
                continue
            if current_tc:
                dialogue_buf.append(line)

        _flush_flat()

        if flat_rows:
            return _entries_from_start_times(flat_rows)

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


def prepare_for_platform(subtitles: list[dict], platform_key: str | dict, filename: str = "") -> list[dict]:
    """Apply deterministic platform delivery rules that do not require rewriting timings by AI."""
    if isinstance(platform_key, dict):
        platform = platform_key
    else:
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

    # ── 5. Strip speaker prefix WITH colon/dash across the whole text block first ──
    # Handles cells where the label is on line 1 and dialogue on line 2
    text = re.sub(r"^[A-Z][A-Z0-9 .'\-/()#&,]{0,60}[:\-]\s*", "", text.lstrip())

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
    def mark_line_limit(item: dict):
        hints = list(item.get("rule_hints", []))
        if "line_limit" not in hints:
            hints.append("line_limit")
        item["rule_hints"] = hints

    split = []
    for sub in subtitles:
        text = sub.get("text", "")
        if _text_fits(text, max_chars, max_lines):
            item = dict(sub)
            item["text"] = _wrap_chunk(text, max_chars)
            if item["text"] != text:
                mark_line_limit(item)
            split.append(item)
            continue

        chunks = _chunk_wrapped_groups(text, max_chars, max_lines)
        if len(chunks) <= 1:
            item = dict(sub)
            item["text"] = _wrap_chunk(text, max_chars)
            if item["text"] != text:
                mark_line_limit(item)
            split.append(item)
            continue

        start = _to_seconds(sub.get("start_time", ""))
        end = _to_seconds(sub.get("end_time", ""))
        if start is None or end is None or end <= start:
            for chunk in chunks:
                item = dict(sub)
                item["text"] = _wrap_chunk(chunk, max_chars)
                mark_line_limit(item)
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
            mark_line_limit(item)
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
        "original_text": "",
        "rule_hints": ["zero_subtitle"],
        "flagged": False,
        "flag_reason": "",
    }
    return [zero] + subtitles


def _looks_like_zero_subtitle(text: str) -> bool:
    upper = (text or "").upper()
    return "STORY:" in upper and "LANG:" in upper


def _show_name_from_filename(filename: str) -> str:
    """
    Produce a clean human-readable show title from a delivery filename.

    Real-world filenames contain internal job numbers, vendor codes, dates,
    and episode identifiers that must be stripped:
      FoodFactoryS2_EpTheNamesBoondi_NGCP_YA90027775_1159556_111620_BMSub (2).docx
      COYOTE_102_TV_As-Broadcast_Dialogue_List.docx
      EVIL_0405_FINAL_TC_IYUNO SDI.srt
      DrPimplePopperPopUPS_EpPopUPSAnAmericanTail_DCP_DFA316439_1153011_102920.doc
      FBoyIsland_S3EP06_InternationalScript.docx
      CAR SOS 2023 COMPS - UNSEEN - FINAL SCRIPT RD503340.docx
      HouseHuntersInternationalS120_EpLiving...
    """
    # Remove file extension
    name = (filename or "PROGRAM").rsplit(".", 1)[0]

    # ── Pass 1: strip while underscores still act as word boundaries ──────
    # Season/episode codes glued directly to show name: HouseHuntersS120, FoodFactoryS2
    name = re.sub(r'S\d{1,3}(?:EP\d+|E\d+)?(?=[A-Z_\-]|$)', ' ', name)
    # Episode tags: _Ep... or -Ep...
    name = re.sub(r'[_\-]Ep[A-Za-z0-9]+', ' ', name)
    # Trailing parenthetical copy numbers: (2), (1)
    name = re.sub(r'\(\s*\d+\s*\)', ' ', name)
    # Internal job IDs glued to show name: DFA316439, YA90027775, RD503340
    name = re.sub(r'[_\-](?:DFA|YA|RD|NGCP|DCP|HGTVP|HGTV|SDI|PAC|IYUNO|BMSUB)\d*', ' ', name, flags=re.IGNORECASE)
    name = re.sub(r'[_\-]\d{6,}', ' ', name)   # _1159556 _111620

    # ── Pass 2: replace underscores/dashes with spaces ────────────────────
    name = re.sub(r"[_\-]+", " ", name)

    # ── Pass 3: strip vendor/delivery keyword tokens ──────────────────────
    _VENDOR_TOKENS = re.compile(
        r'\b(?:BMSUB|CCSL|CDSL|NGCP|DCP|DFA|SDI|PAC|IYUNO|FINAL|UNSEEN|COMPS|'
        r'HGTVP|HGTV|SU|ENG|CONVERTED|'
        r'AS\s*BROADCAST|DIALOGUE\s*LIST|INTERNATIONAL\s*SCRIPT|'
        r'TV|UHD|HD|SD|RD|YA|TC|EP\s*\w+|S\d+E\d+|S\d+EP\d+)\b',
        re.IGNORECASE
    )
    name = _VENDOR_TOKENS.sub(" ", name)

    # ── Pass 4: strip remaining numeric junk ──────────────────────────────
    # Long numeric job IDs (6+ digits)
    name = re.sub(r'\b\d{6,}\b', " ", name)
    # Leftover season codes: standalone S1, S2 etc. after spaces
    name = re.sub(r'\bS\d{1,3}\b', " ", name)
    # Internal job IDs: 2-4 uppercase letters followed by 4+ digits
    name = re.sub(r'\b[A-Z]{1,4}\d{4,}\b', " ", name)

    # ── Final cleanup ──────────────────────────────────────────────────────
    name = re.sub(r"\s+", " ", name).strip()
    name = name.strip(" .-,()")

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
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if lines and re.match(r"^\d+$", lines[-1]):
        lines = lines[:-1]
    return "\n".join(lines).strip()


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
    match = re.match(r"^(\d{1,3}):(\d{2}):(\d{2})[,.](\d{1,4})$", tc)
    if not match:
        return None
    h, m, s, ms_str = match.groups()
    ms = int(ms_str[:3].ljust(3, '0'))
    raw_seconds = int(h) * 3600 + int(m) * 60 + int(s) + ms / 1000.0
    # Snap to nearest 25 FPS frame exactly
    return round(raw_seconds * _FPS) / _FPS


def _from_seconds(seconds: float) -> str:
    frames_total = round(seconds * _FPS)
    s, f = divmod(frames_total, _FPS)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    ms = round((f / _FPS) * 1000)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(ms):03d}"


def _renumber(entries: list[dict], gap: float = 0.0) -> list[dict]:
    """Renumber and KEEP every entry that has text + a start time.

    NEVER drop a subtitle just because its end time is missing — instead
    infer the end from the next subtitle's start (or a default 3s span).
    This guarantees no dialogue is silently lost during conversion.
    """
    result = []
    # Filter to keep entries that have usable text and a start time.
    kept = [e for e in entries if e.get("text", "").strip() and e.get("start_time")]
    for i, entry in enumerate(kept, start=1):
        item = dict(entry)
        start = entry.get("start_time")
        end = entry.get("end_time")
        # Infer end time if missing: use next start (minus gap) or +3s.
        if not end:
            nxt = kept[i] if i < len(kept) else None
            if nxt and nxt.get("start_time"):
                nxt_secs = _to_seconds(nxt.get("start_time")) or 0
                cur_secs = _to_seconds(start) or 0
                end_secs = max(nxt_secs - gap, cur_secs + 0.2)
                end = _from_seconds(end_secs)
            else:
                cur_secs = _to_seconds(start) or 0
                end = _from_seconds(cur_secs + 3.0)
        item["start_time"] = start
        item["end_time"] = end
        item["id"] = i
        result.append(item)
    return result
