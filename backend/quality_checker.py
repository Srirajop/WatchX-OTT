# quality_checker.py — Checks AND auto-fixes cleaned subtitle files
# Based on REAL rules from OTT Clients Protocol Excel images
# Two modes: check_quality (report defects) and auto_fix (fix what can be fixed)

import re
from platform_rules import get_platform, UNIVERSAL_GUIDELINES, get_profanity_table


# ─── AUTO-FIX PASS ───────────────────────────────────────────────────────────

def _capitalize_line(line: str) -> str:
    # If it starts with ellipsis, keep lowercase as it indicates mid-sentence continuation
    if line.startswith('...'):
        return line
    # Find the first alphabetic character and capitalize it if it's lower
    m = re.search(r'[a-zA-Z]', line)
    if m:
        idx = m.start()
        prefix = line[:idx]
        if not prefix.endswith('...'):
            return line[:idx] + line[idx].upper() + line[idx+1:]
    return line


def _split_line(line: str, max_chars: int) -> str:
    """
    Split a single line over max_chars into max 2 lines at a natural word boundary.
    Preserves italics wrapping if the entire line was wrapped in <i>...</i>.
    """
    line = line.strip()
    if not line:
        return line
        
    # Check if the line is fully wrapped in italics
    has_italics = line.startswith('<i>') and line.endswith('</i>')
    
    clean_line = re.sub(r'<[^>]+>', '', line)
    if len(clean_line) <= max_chars:
        return line

    words = clean_line.split()
    if len(words) <= 1:
        # Single word too long — keep as is
        return line

    # Find best split point — left part must be <= max_chars
    # Prefer split near the middle for balanced lines
    best_split = None
    best_balance = float('inf')

    for i in range(1, len(words)):
        left = ' '.join(words[:i])
        right = ' '.join(words[i:])
        if len(left) <= max_chars and len(right) <= max_chars:
            balance = abs(len(left) - len(right))
            if balance < best_balance:
                best_balance = balance
                best_split = i

    if best_split:
        left_part = ' '.join(words[:best_split])
        right_part = ' '.join(words[best_split:])
        if has_italics:
            return f"<i>{left_part}</i>\n<i>{right_part}</i>"
        else:
            return f"{left_part}\n{right_part}"
    else:
        return line


def auto_fix_subtitles(subtitles: list, platform_key: str) -> list:
    """
    Apply platform rules automatically in Python — 100% reliable.
    Fixes: profanity replacement, double spaces, punctuation, sentence case,
           line splitting at char limit, HOH/EMT removal, filler removal.
    Called AFTER LLM polish.
    """
    platform = get_platform(platform_key)
    max_chars = platform.get("max_chars_per_line", 42)
    max_chars_italics = platform.get("max_chars_italics", max_chars)
    profanity_table = get_profanity_table(platform_key)
    remove_elements = platform.get("remove_elements", [])

    fixed = []
    for sub in subtitles:
        text = sub.get("text", "")
        if not text:
            fixed.append(sub)
            continue

        # 1. Remove HOH/EMT elements (Discovery/DMAX requirement)
        if "HOH" in remove_elements or "EMT" in remove_elements:
            text = re.sub(r'\[MUSIC[^\]]*\]', '', text, flags=re.IGNORECASE)
            text = re.sub(r'\[APPLAUSE\]', '', text, flags=re.IGNORECASE)
            text = re.sub(r'\[LAUGHTER\]', '', text, flags=re.IGNORECASE)
            text = re.sub(r'\[CHEERING\]', '', text, flags=re.IGNORECASE)
            text = re.sub(r'\[[^\]]*sound[^\]]*\]', '', text, flags=re.IGNORECASE)
            text = re.sub(r'\[[^\]]*music[^\]]*\]', '', text, flags=re.IGNORECASE)

        # 2. Remove fillers (Guide Discovery requirement)
        if "fillers" in remove_elements:
            text = re.sub(r'\b(ugh|hmm|erm|ah|oh)\b[\.,]?\s*', '', text, flags=re.IGNORECASE)

        # 3. Replace profanity per platform table
        for word, replacement in profanity_table.items():
            text = re.sub(r'\b' + re.escape(word) + r'\b', replacement, text, flags=re.IGNORECASE)

        # 4. Fix double spaces
        text = re.sub(r'  +', ' ', text)

        # 5. Fix space before punctuation
        text = re.sub(r' ([.,!?;:])', r'\1', text)

        # 6. Fix sentence case — first word capitalised (respects hyphens and ellipses)
        text = '\n'.join(_capitalize_line(line.strip()) for line in text.split('\n'))

        # 7. Split lines exceeding char limit at word boundaries (respects italics limit)
        split_lines = []
        for line in text.split('\n'):
            limit = max_chars_italics if ("<i>" in line or "</i>" in line) and "max_chars_italics" in platform else max_chars
            split_lines.append(_split_line(line, limit))
        text = '\n'.join(split_lines)

        # 8. Strip trailing/leading whitespace per line
        text = '\n'.join(l.strip() for l in text.split('\n'))
        text = text.strip()

        sub = dict(sub)
        sub["text"] = text
        fixed.append(sub)

    return fixed


# ─── QUALITY CHECK ───────────────────────────────────────────────────────────

def check_quality(subtitles: list, platform_key: str, filename: str) -> dict:
    """
    Run all quality checks on a subtitle list.
    Returns defects with line number, severity, description, suggestion.
    """
    platform = get_platform(platform_key)
    defects = []

    defects += check_file_naming(filename, platform)
    defects += check_zero_subtitle(subtitles, platform)
    defects += check_each_line(subtitles, platform)
    defects += check_profanity(subtitles, platform_key)
    defects += check_spacing_punctuation(subtitles)
    defects += check_hoh_emt(subtitles, platform)
    defects += check_universal_guidelines(subtitles)

    total = len(subtitles)
    defect_lines = len(set(d["line_id"] for d in defects if d.get("line_id")))

    return {
        "defects": defects,
        "total_defects": len(defects),
        "defect_lines": defect_lines,
        "total_lines": total,
        "clean_lines": total - defect_lines,
        "is_ready_for_delivery": len(defects) == 0,
        "platform": platform["name"],
        "filename": filename,
    }


def check_file_naming(filename: str, platform: dict) -> list:
    defects = []
    naming_format = platform.get("file_naming_format", "")
    if not naming_format:
        return defects
    if "EHD_" in naming_format:
        pattern = r'^EHD_\d{6}[A-Z]_[A-Z]{3}\.PAC$'
        if not re.match(pattern, filename, re.IGNORECASE):
            defects.append({
                "type": "FILE_NAMING",
                "severity": "critical",
                "line_id": None,
                "description": f"File '{filename}' does not match required format '{naming_format}'. Wrong name = automatic OTT rejection.",
                "suggestion": f"Rename to: {naming_format}"
            })
    return defects


def check_zero_subtitle(subtitles: list, platform: dict) -> list:
    defects = []
    if not platform.get("zero_subtitle_required", False):
        return defects
    if not subtitles:
        defects.append({
            "type": "ZERO_SUBTITLE_MISSING",
            "severity": "critical",
            "line_id": None,
            "description": "No subtitles found. Zero subtitle is required for this platform.",
            "suggestion": "Add zero subtitle: timecode 00:00:00:00 to 00:00:00:08 with show name, STORY: [ID], LANG: ENG"
        })
        return defects
    first = subtitles[0]
    text = first.get("text", "")
    text_upper = text.upper()

    # Check required fields: STORY: and LANG:
    missing_fields = []
    if "STORY:" not in text_upper:
        missing_fields.append("STORY: [programme ID]")
    if "LANG:" not in text_upper:
        missing_fields.append("LANG: ENG")

    if missing_fields:
        defects.append({
            "type": "ZERO_SUBTITLE_INVALID",
            "severity": "critical",
            "line_id": first.get("id"),
            "description": f"First subtitle is not a valid zero subtitle. Missing: {', '.join(missing_fields)}. Any mistake = file fails to transmit.",
            "suggestion": "Zero subtitle must have: Show name, Episode, Language, STORY: [programme ID], LANG: ENG"
        })

    # Verify zero subtitle starts at 00:00:00,000
    start = first.get("start_time", "")
    if start and not start.startswith("00:00:00"):
        defects.append({
            "type": "ZERO_SUBTITLE_TIMECODE",
            "severity": "critical",
            "line_id": first.get("id"),
            "description": f"Zero subtitle must start at 00:00:00:00 but starts at {start}. GTS Pro will reject the file.",
            "suggestion": "Set zero subtitle in-time to 00:00:00:00 and out-time to 00:00:00:08 (or at least 1.08s)."
        })
    return defects


def check_each_line(subtitles: list, platform: dict) -> list:
    defects = []
    max_chars = platform.get("max_chars_per_line", 42)
    max_chars_italics = platform.get("max_chars_italics", max_chars - 1)
    max_lines_per_sub = platform.get("max_lines", 2)
    max_duration = platform.get("max_duration_seconds", 7.0)
    min_duration = platform.get("min_duration_seconds", 1.0)
    max_cps = platform.get("reading_speed_max_cps", 21)
    target_cps = platform.get("reading_speed_target_cps", 17)

    for sub in subtitles:
        sub_id = sub.get("id")
        text = sub.get("text", "")
        if not text:
            continue
        if _is_zero_subtitle(text):
            continue
        lines = text.split("\n")

        # Too many lines
        if len(lines) > max_lines_per_sub:
            defects.append({
                "type": "TOO_MANY_LINES",
                "severity": "error",
                "line_id": sub_id,
                "description": f"Subtitle has {len(lines)} lines. Max is {max_lines_per_sub} for {platform['name']}.",
                "suggestion": "Split into separate subtitles.",
                "text": text
            })

        # Line too long
        for i, line in enumerate(lines):
            clean = re.sub(r'<[^>]+>', '', line)
            limit = max_chars_italics if ("<i>" in line or "</i>" in line) and "max_chars_italics" in platform else max_chars
            if len(clean) > limit:
                description = f"Line {i+1} is {len(clean)} chars. Max is {limit} for {platform['name']} (italics limit: {max_chars_italics})." if limit == max_chars_italics else f"Line {i+1} is {len(clean)} chars. Max is {limit} for {platform['name']}."
                defects.append({
                    "type": "LINE_TOO_LONG",
                    "severity": "error",
                    "line_id": sub_id,
                    "description": description,
                    "suggestion": f"Split at a natural phrase boundary to fit within {limit} characters.",
                    "text": text
                })

        # Duration checks (only if timecodes present)
        start = sub.get("start_time", "")
        end = sub.get("end_time", "")
        if start and end:
            duration = parse_duration(start, end)
            if duration is not None and duration >= 0:
                if duration < min_duration:
                    defects.append({
                        "type": "DURATION_TOO_SHORT",
                        "severity": "warning",
                        "line_id": sub_id,
                        "description": f"Duration {duration:.2f}s is below minimum {min_duration}s for {platform['name']}.",
                        "suggestion": f"Extend the out-time by at least {min_duration - duration:.2f}s.",
                        "text": text
                    })
                if duration > max_duration:
                    defects.append({
                        "type": "DURATION_TOO_LONG",
                        "severity": "warning",
                        "line_id": sub_id,
                        "description": f"Duration {duration:.2f}s exceeds maximum {max_duration}s for {platform['name']}.",
                        "suggestion": "Split into multiple subtitles or tighten the out-time.",
                        "text": text
                    })
                # Reading speed — GTS Pro/Iyuno standard:
                # CPS = number of non-whitespace characters / duration in seconds
                # This matches what GTS Pro counts: visible characters only
                visible_chars = len(re.sub(r'\s', '', re.sub(r'<[^>]+>', '', text)))
                if duration > 0 and visible_chars > 0:
                    cps = visible_chars / duration
                    if cps > max_cps:
                        defects.append({
                            "type": "READING_SPEED_EXCEEDED",
                            "severity": "error",
                            "line_id": sub_id,
                            "description": f"Reading speed {cps:.1f} CPS exceeds max {max_cps} CPS for {platform['name']}. This is a hard limit — cannot be crossed.",
                            "suggestion": "Shorten the subtitle text or extend the duration.",
                            "text": text
                        })
                    elif cps > target_cps:
                        defects.append({
                            "type": "READING_SPEED_HIGH",
                            "severity": "warning",
                            "line_id": sub_id,
                            "description": f"Reading speed {cps:.1f} CPS is above target {target_cps} CPS for {platform['name']}. Yellow subtitle — acceptable but review.",
                            "suggestion": "Consider shortening or extending duration if possible.",
                            "text": text
                        })

    return defects


def check_profanity(subtitles: list, platform_key: str) -> list:
    defects = []
    profanity_table = get_profanity_table(platform_key)
    if not profanity_table:
        return defects
    for sub in subtitles:
        text = sub.get("text", "")
        for word, replacement in profanity_table.items():
            if re.search(r'\b' + re.escape(word) + r'\b', text, re.IGNORECASE):
                defects.append({
                    "type": "PROFANITY_NOT_REPLACED",
                    "severity": "error",
                    "line_id": sub.get("id"),
                    "description": f"'{word}' must be replaced with '{replacement}' for {platform_key}.",
                    "suggestion": f"Replace '{word}' → '{replacement}'",
                    "text": text
                })
    return defects


def check_spacing_punctuation(subtitles: list) -> list:
    defects = []
    for sub in subtitles:
        sub_id = sub.get("id")
        text = sub.get("text", "")
        if _is_zero_subtitle(text):
            continue
        issues = []

        if "  " in text:
            issues.append("double space")
        if re.search(r' [.,!?;:]', text):
            issues.append("space before punctuation")
        if re.search(r'[!]{2,}', text):
            issues.append("double exclamation marks (!!) — not allowed")
        if re.search(r'[?]{2,}', text):
            issues.append("double question marks (??) — not allowed")
        if re.search(r'\.{4,}', text):
            issues.append("more than 3 dots — use exactly 3 for ellipsis")
        if text != text.strip():
            issues.append("leading or trailing whitespace")
        stripped = text.strip()
        if stripped and stripped[0].islower() and not stripped.startswith('...'):
            issues.append("starts with lowercase letter")
        # Check for orphaned hyphen at start (two speaker format)
        for line in text.split('\n'):
            if line.startswith('- ') and len(line) < 3:
                issues.append("empty speaker line (just hyphen)")

        if issues:
            defects.append({
                "type": "FORMATTING_DEFECT",
                "severity": "error",
                "line_id": sub_id,
                "description": f"Formatting issues: {'; '.join(issues)}",
                "suggestion": "Fix the listed formatting issues before delivery.",
                "text": text
            })
    return defects


def check_hoh_emt(subtitles: list, platform: dict) -> list:
    defects = []
    remove_elements = platform.get("remove_elements", [])
    if "HOH" not in remove_elements and "EMT" not in remove_elements:
        return defects
    hoh_patterns = [
        r'\[MUSIC[^\]]*\]', r'\[APPLAUSE\]', r'\[LAUGHTER\]', r'\[CHEERING\]',
        r'\[GUNSHOT\]', r'\[EXPLOSION\]', r'\(narrator\)', r'\(narrating\)',
        r'\[.*?music.*?\]', r'\[.*?sound.*?\]',
    ]
    for sub in subtitles:
        text = sub.get("text", "")
        for pattern in hoh_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                defects.append({
                    "type": "HOH_EMT_ELEMENT",
                    "severity": "error",
                    "line_id": sub.get("id"),
                    "description": f"HOH/EMT element found. Must be removed for {platform['name']}.",
                    "suggestion": "Remove this accessibility marker completely.",
                    "text": text
                })
                break
    return defects


def check_universal_guidelines(subtitles: list) -> list:
    """
    Check SDI House Protocol universal guidelines.
    These are TIMING rules — only applicable when timecodes are present.
    """
    defects = []
    # Universal guidelines are about frame gaps and shot changes
    # These can only be checked when timecodes are available
    # For now we report if we detect timing that looks wrong
    prev_end = None
    fps = 25  # PAL standard

    for sub in subtitles:
        start = sub.get("start_time", "")
        end = sub.get("end_time", "")
        if not start or not end:
            prev_end = None
            continue

        start_sec = _tc_to_seconds(start)
        end_sec = _tc_to_seconds(end)
        if start_sec is None or end_sec is None:
            prev_end = None
            continue

        # Check gap from previous subtitle
        if prev_end is not None:
            gap_sec = start_sec - prev_end
            gap_frames = round(gap_sec * fps)

            # SDI House Protocol: gaps must be 2 frames or 12+ frames
            # Never 3-11 frames
            if 3 <= gap_frames <= 11:
                defects.append({
                    "type": "INVALID_GAP",
                    "severity": "warning",
                    "line_id": sub.get("id"),
                    "description": f"Gap of {gap_frames} frames between subtitles. SDI House Protocol says gaps must be exactly 2 frames or 12+ frames. Never 3-11 frames.",
                    "suggestion": "Extend the out-time of the previous subtitle to close to 2 frames, or leave 12+ frames gap.",
                    "text": sub.get("text", "")
                })

        prev_end = end_sec

    return defects


def _is_zero_subtitle(text: str) -> bool:
    upper = (text or "").upper()
    return "STORY:" in upper and "LANG:" in upper


def parse_duration(start: str, end: str):
    try:
        return _tc_to_seconds(end) - _tc_to_seconds(start)
    except:
        return None


def _tc_to_seconds(tc: str):
    try:
        tc = tc.replace(',', '.').replace(';', ':')
        parts = tc.split(':')
        if len(parts) == 4:
            h, m, s, f = parts
            return int(h)*3600 + int(m)*60 + float(s) + int(f)/25
        elif len(parts) == 3:
            h, m, s = parts
            return int(h)*3600 + int(m)*60 + float(s)
        return None
    except:
        return None
