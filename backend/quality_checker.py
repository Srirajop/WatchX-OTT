# quality_checker.py - Checks AND auto-fixes cleaned subtitle files
# Based on REAL rules from OTT Clients Protocol Excel images
# Two modes: check_quality (report defects) and auto_fix (fix what can be fixed)

import re
from platform_rules import get_platform, UNIVERSAL_GUIDELINES, get_profanity_table
from italic_formatter import apply_italics_rules, has_italics_errors


# --- HELPERS ---

_NUMS_1_10 = {
    '0': 'zero', '1': 'one', '2': 'two', '3': 'three', '4': 'four',
    '5': 'five', '6': 'six', '7': 'seven', '8': 'eight', '9': 'nine', '10': 'ten'
}
_NUMS_1_9 = {k: v for k, v in _NUMS_1_10.items() if k not in ('10',)}
_NUMS_0_9 = _NUMS_1_10.copy()

# UK -> US spelling corrections (most common broadcast subtitle issues)
_UK_US = {
    r'\bcolour\b': 'color', r'\bcolours\b': 'colors',
    r'\bfavourite\b': 'favorite', r'\bfavourites\b': 'favorites',
    r'\bneighbour\b': 'neighbor', r'\bneighbours\b': 'neighbors',
    r'\bhonour\b': 'honor', r'\bhonours\b': 'honors',
    r'\bbehaviour\b': 'behavior', r'\bbehaviours\b': 'behaviors',
    r'\bflavour\b': 'flavor', r'\bflavours\b': 'flavors',
    r'\blabour\b': 'labor', r'\blabours\b': 'labors',
    r'\bhumour\b': 'humor', r'\btumour\b': 'tumor',
    r'\brealise\b': 'realize', r'\brealises\b': 'realizes', r'\brealised\b': 'realized',
    r'\borganise\b': 'organize', r'\borganised\b': 'organized',
    r'\brecognise\b': 'recognize', r'\brecognised\b': 'recognized',
    r'\bcentre\b': 'center', r'\btheatre\b': 'theater',
    r'\blicence\b': 'license', r'\bdefence\b': 'defense',
    r'\bprogramme\b': 'program', r'\bprogrammes\b': 'programs',
    r'\btravelling\b': 'traveling', r'\bcancelled\b': 'canceled',
    r'\bfulfil\b': 'fulfill', r'\benrol\b': 'enroll',
    r'\bjoalise\b': 'realize',
}


def _fix_numbers_in_text(text: str, num_map: dict) -> str:
    """Replace standalone digit strings with their word equivalents."""
    def _replacer(m):
        n = m.group(0)
        # Skip years, times, addresses, measurements (context heuristics)
        pre = text[:m.start()]
        post = text[m.end():]
        # Skip if preceded by $ / % or followed by % / ft / mph / km etc.
        if re.search(r'[$%]$', pre) or re.search(r'^[%s]', post):
            return n
        if re.search(r'(st|nd|rd|th|ft|in|cm|mm|km|kg|lb|mph|kph|am|pm)$', post[:3], re.IGNORECASE):
            return n
        # Skip 4-digit numbers (years like 2024)
        if len(n) == 4 and n.startswith(('19', '20')):
            return n
        return num_map.get(n, n)
    # Match standalone numbers (not part of larger numbers)
    pattern = r'\b(' + '|'.join(re.escape(k) for k in sorted(num_map, key=len, reverse=True)) + r')\b'
    return re.sub(pattern, _replacer, text)


def _fix_us_spelling(text: str) -> str:
    """Fix British -> US English spelling."""
    for pattern, replacement in _UK_US.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


def _strip_remaining_char_names(text: str) -> str:
    """Last-resort removal of ALL-CAPS character name labels at line start.
    Preserves <i>/<b> italic/bold tags — stashes them, strips speaker label, restores."""
    lines = text.split('\n')
    cleaned = []
    for line in lines:
        # Stash italic/bold tags so they survive speaker-label stripping
        line = line.replace('<i>', '__IO__').replace('</i>', '__IC__')
        line = line.replace('<b>', '__BO__').replace('</b>', '__BC__')
        # Pattern: ALL-CAPS word(s) followed by : or - at start of line
        stripped = re.sub(r'^[A-Z][A-Z0-9 .\'/()]{1,40}[:\-]\s*', '', line)
        if stripped.strip():  # don't blank the whole line
            line = stripped
        # Restore tags
        line = line.replace('__IO__', '<i>').replace('__IC__', '</i>')
        line = line.replace('__BO__', '<b>').replace('__BC__', '</b>')
        cleaned.append(line)
    return '\n'.join(cleaned)

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
    Apply platform rules automatically in Python - 100% reliable catch-all.
    Called AFTER the LLM clean pass to fix anything the LLM missed.
    Fixes: profanity, punctuation, sentence case, HOH removal, filler removal,
           two-speaker hyphen format, number words, character name stripping,
           italics formatting, US spelling, line splitting.
    """
    platform = get_platform(platform_key)
    max_chars = platform.get("max_chars_per_line", 42)
    max_chars_italics = platform.get("max_chars_italics", max_chars)
    profanity_table = get_profanity_table(platform_key)
    remove_elements = platform.get("remove_elements", [])
    rules_text = " ".join(platform.get("rules", []))
    speaker_fmt = platform.get("two_speaker_format", "")

    # Determine number rule from platform rules
    if "1-10 in words" in rules_text or "Numbers 1-10" in rules_text:
        num_map = _NUMS_1_10
    elif "0-9 written out" in rules_text:
        num_map = _NUMS_0_9
    elif "1-9" in rules_text or "spell out numbers 1-9" in rules_text.lower():
        num_map = _NUMS_1_9
    else:
        num_map = None

    fixed = []
    for sub in subtitles:
        text = sub.get("text", "")
        if not text:
            fixed.append(sub)
            continue

        # 1. Remove HOH/EMT elements
        if "HOH" in remove_elements or "EMT" in remove_elements:
            text = re.sub(r'\[MUSIC[^\]]*\]', '', text, flags=re.IGNORECASE)
            text = re.sub(r'\[APPLAUSE[^\]]*\]', '', text, flags=re.IGNORECASE)
            text = re.sub(r'\[LAUGHTER[^\]]*\]', '', text, flags=re.IGNORECASE)
            text = re.sub(r'\[CHEERING[^\]]*\]', '', text, flags=re.IGNORECASE)
            text = re.sub(r'\[SINGING[^\]]*\]', '', text, flags=re.IGNORECASE)
            text = re.sub(r'\[[^\]]*(?:sound|music|applause|laughter|singing|cheering|gunshot|explosion)[^\]]*\]', '', text, flags=re.IGNORECASE)
            text = re.sub(r'\(.*?(?:music|singing|narrator|narrating|chuckles|laughs|sighs|gasps|crying|sobbing|whimpering).*?\)', '', text, flags=re.IGNORECASE)
            # Remove any remaining [...] blocks that look like HOH
            text = re.sub(r'\[[A-Z ]+\]', '', text)

        # 2. Remove stage directions
        if "stage_directions" in remove_elements:
            text = re.sub(r'\([^)]{1,100}\)', '', text)
            text = re.sub(r'\[[^\]]{1,100}\]', '', text)

        # 3. Remove character name labels
        if "character_names" in remove_elements:
            text = _strip_remaining_char_names(text)

        # 4. Remove fillers
        if "fillers" in remove_elements:
            text = re.sub(r'\b(u+gh+|h+mm+|erm+|a+h+|o+h+|u+m+|u+h+)\b[\.,]?\s*', '', text, flags=re.IGNORECASE)

        # 5. Replace profanity per platform table
        for word, replacement in profanity_table.items():
            text = re.sub(r'\b' + re.escape(word) + r'\b', replacement, text, flags=re.IGNORECASE)

        if "asterisks (****)" in rules_text:
            text = re.sub(r'\*bleep\*|\[bleep\]|\(bleep\)', '****', text, flags=re.IGNORECASE)

        # 6. Fix double spaces
        text = re.sub(r'  +', ' ', text)

        # 7. Fix space before punctuation
        text = re.sub(r' ([.,!?;:])', r'\1', text)

        # 8. Fix double/mixed punctuation
        text = re.sub(r'!!+', '!', text)
        text = re.sub(r'\?\?+', '?', text)
        text = re.sub(r'[!?][?!]+', '!', text)  # !? ?! etc

        # 9. Ellipsis must be exactly 3 dots
        text = re.sub(r'\.{4,}', '...', text)
        # Convert exactly 2 dots to 3 dots, using lookbehinds to prevent touching existing 3 dots
        text = re.sub(r'(?<!\.)\.{2}(?!\.)', '...', text)

        # 10. Two-speaker hyphen format
        if speaker_fmt == "hyphen_no_space":
            text = re.sub(r'^- ', '-', text, flags=re.MULTILINE)
        elif speaker_fmt == "hyphen_with_space":
            text = re.sub(r'^-([^\-\s])', r'- \1', text, flags=re.MULTILINE)

        # --- PLATFORM-SPECIFIC TEXTUAL RULE ENFORCEMENT ---

        # 10a. "Always use quotation marks instead of apostrophes for quotes"
        if "quotation marks instead of apostrophes" in rules_text:
            text = re.sub(r"(^|\s)'([^']*)'(\s|$|[.,?!])", r'\1"\2"\3', text)
            
        # 10b. "Do not use &, <, >, degree or copyright symbols"
        # For platforms like discovery_scripps that forbid ALL text styles,
        # first strip SRT/HTML markup tags cleanly (e.g. <i>text</i> -> text)
        # THEN remove any remaining bare < > characters.
        if "&, <, >, degree or copyright symbols" in rules_text:
            text = re.sub(r'<[^>]+>', '', text)   # strip all HTML/SRT tags cleanly
            text = text.replace('&', 'and')
            text = text.replace('<', '')
            text = text.replace('>', '')
            text = text.replace('©', '')
            text = text.replace('°', ' degrees')

            
        # 10c. "No periods for acronyms: FBI, NASA, NATO"
        if "no periods for acronyms" in rules_text:
            def remove_periods(m): return m.group(0).replace('.', '')
            text = re.sub(r'\b([A-Z])\.([A-Z])\.([A-Z])?\.?', remove_periods, text)
            
        # 10d. "Use ellipsis without space at start if subtitle starts mid-sentence"
        if "ellipsis without space at start" in rules_text:
            text = re.sub(r'^\.\.\.\s+', '...', text, flags=re.MULTILINE)

        # 10e. "Song lyrics italicised, upper case at beginning of line"
        if "upper case at beginning of line" in rules_text and "song" in rules_text:
            def upper_lyric(m): return m.group(1) + m.group(2).upper()
            text = re.sub(r'(♪\s*)([a-z])', upper_lyric, text)
            
        # 10f. "No punctuation at end of song line except ? and !"
        if "no punctuation at end of song line" in rules_text:
            lines = text.split('\n')
            for i, line in enumerate(lines):
                if '♪' in line or '♫' in line:
                    lines[i] = re.sub(r'[,.]+(\s*(?:</i>)?\s*)$', r'\1', line)
            text = '\n'.join(lines)
            
        # 10g. "STORY and LANG must be capitalised with colon followed by space"
        if "story and lang must be capitalised" in rules_text:
            text = re.sub(r'(?i)\bstory\s*:', 'STORY:', text)
            text = re.sub(r'(?i)\blang\s*:', 'LANG:', text)

        # 10h. "Double hyphens (--) for abrupt interruptions"
        if "double hyphens (--)" in rules_text:
            text = re.sub(r'—', '--', text)  # convert em-dash to double hyphen

        # 11. Fix sentence case per line (respects ellipsis continuations)
        text = '\n'.join(_capitalize_line(line.strip()) for line in text.split('\n'))

        # 12. Number-to-word conversion
        if num_map:
            lines_num = []
            for line in text.split('\n'):
                # Don't modify content inside <i>...</i> for numbers (italics already set)
                lines_num.append(_fix_numbers_in_text(line, num_map))
            text = '\n'.join(lines_num)

        # 13. US English spelling fix
        text = _fix_us_spelling(text)

        # 14. Split lines exceeding char limit
        split_lines = []
        for line in text.split('\n'):
            limit = max_chars_italics if ('<i>' in line or '</i>' in line) and 'max_chars_italics' in platform else max_chars
            split_lines.append(_split_line(line, limit))
        text = '\n'.join(split_lines)

        # 15. Strip whitespace per line and remove blank lines
        lines_final = [l.strip() for l in text.split('\n') if l.strip()]
        text = '\n'.join(lines_final).strip()

        sub = dict(sub)
        sub["text"] = text
        fixed.append(sub)

    # Final pass: apply platform italics rules (song lyrics, VO, foreign words etc.)
    fixed = apply_italics_rules(fixed, platform_key)

    return fixed


# ─── QUALITY CHECK ───────────────────────────────────────────────────────────

def check_quality(subtitles: list, platform_key: str, filename: str) -> dict:
    """
    Run all quality checks on a subtitle list.
    AUTO-FIXES everything fixable first, then reports only what remains.
    Returns fixed subtitles + remaining defects.
    """
    platform = get_platform(platform_key)

    # Step 1: Auto-fix everything fixable in Python
    fixed_subtitles = auto_fix_subtitles(subtitles, platform_key)

    # Step 2: Check the FIXED subtitles — only real remaining problems reported
    defects = []
    defects += check_file_naming(filename, platform)
    defects += check_zero_subtitle(fixed_subtitles, platform)
    defects += check_each_line(fixed_subtitles, platform)
    defects += check_profanity(fixed_subtitles, platform_key)
    defects += check_spacing_punctuation(fixed_subtitles)
    defects += check_hoh_emt(fixed_subtitles, platform)
    defects += check_universal_guidelines(fixed_subtitles)
    defects += has_italics_errors(fixed_subtitles, platform_key)
    defects += check_platform_specific_rules(fixed_subtitles, platform)

    # Separate hard errors from warnings/info
    errors = [d for d in defects if d.get('severity') in ('critical', 'error')]
    warnings = [d for d in defects if d.get('severity') == 'warning']
    info = [d for d in defects if d.get('severity') == 'info']

    total = len(fixed_subtitles)
    defect_lines = len(set(d["line_id"] for d in defects if d.get("line_id")))

    return {
        "defects": defects,
        "total_defects": len(defects),
        "error_count": len(errors),
        "warning_count": len(warnings),
        "info_count": len(info),
        "defect_lines": defect_lines,
        "total_lines": total,
        "clean_lines": total - defect_lines,
        # Ready for delivery = zero critical/error defects (warnings are acceptable)
        "is_ready_for_delivery": len(errors) == 0,
        "platform": platform["name"],
        "filename": filename,
        "subtitles": fixed_subtitles,  # return the auto-fixed version
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
        return defects  # No subtitles at all — a different check will catch this

    first = subtitles[0]
    text = first.get("text", "")
    text_upper = text.upper()

    # Only check zero subtitle format if the first subtitle starts at 00:00 (i.e. it looks like a zero subtitle)
    start = first.get("start_time", "")
    looks_like_zero_position = (not start) or start.startswith("00:00:00")

    if looks_like_zero_position:
        # It's in position 0 — check if it has the required fields
        missing_fields = []
        if "STORY:" not in text_upper:
            missing_fields.append("STORY: [programme ID]")
        if "LANG:" not in text_upper:
            missing_fields.append("LANG: ENG")

        if missing_fields:
            defects.append({
                "type": "ZERO_SUBTITLE_INVALID",
                "severity": "warning",
                "line_id": first.get("id"),
                "description": f"First subtitle may be missing zero subtitle fields: {', '.join(missing_fields)}. Required for {platform['name']}.",
                "suggestion": "Zero subtitle must have: Show name, Episode, Language, STORY: [programme ID], LANG: ENG at 00:00:00:00"
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
                            "severity": "info",  # warning only — does NOT block delivery
                            "line_id": sub_id,
                            "description": f"Reading speed {cps:.1f} CPS is above target {target_cps} CPS (max allowed: {max_cps} CPS). Acceptable for delivery but review if possible.",
                            "suggestion": "Shorten text or extend duration slightly if the timing allows.",
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

        # Lowercase check — info only (many legit mid-sentence continuations)
        lowercase_issues = []
        for line in text.split('\n'):
            ln = line.strip()
            if not ln or _is_zero_subtitle(ln):
                continue
            check_line = ln
            if check_line.startswith('-'):
                check_line = check_line[1:].lstrip()
            if not check_line or check_line.startswith('...'):
                continue
            check_line_no_tag = re.sub(r'^(<i>|</i>|<b>|</b>)+', '', check_line).strip()
            if check_line_no_tag and check_line_no_tag[0].islower():
                lowercase_issues.append(f"'{ln[:30]}...'" if len(ln) > 30 else f"'{ln}'")
                break

        # Check for orphaned hyphen at start (two speaker format)
        for line in text.split('\n'):
            if line.strip() in ('-', '- ', '\u2013'):
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
        if lowercase_issues:
            defects.append({
                "type": "CAPITALIZATION_NOTE",
                "severity": "info",
                "line_id": sub_id,
                "description": f"Line(s) start lowercase — verify these are intentional mid-sentence continuations: {'; '.join(lowercase_issues)}",
                "suggestion": "If not a mid-sentence continuation, capitalize the first word.",
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


def check_platform_specific_rules(subtitles: list, platform: dict) -> list:
    defects = []
    rules = platform.get("rules", [])
    rules_text = " ".join(rules).lower()

    if not subtitles: return defects

    # 1. End credit Iyuno check — INFO only (subtitler adds this in GTS Pro, not in script)
    if "subtitling by iyuno" in rules_text:
        found = any("subtitling by iyuno" in (s.get("text", "") or "").lower() for s in subtitles)
        if not found:
            defects.append({
                "type": "END_CREDIT_REMINDER",
                "severity": "info",
                "line_id": subtitles[-1].get("id"),
                "description": "Reminder: Platform requires 'Subtitling by Iyuno' end credit at start of credits roll (2-4 secs). Add this in GTS Pro when spotting the end credits.",
                "suggestion": "In GTS Pro: add a subtitle 'Subtitling by Iyuno' timed 2-4 seconds at the start of the credits roll."
            })

    # 2. Beeped profanity asterisks — warn only if bleep placeholder found
    if "asterisks (****)" in rules_text:
        for sub in subtitles:
            text = sub.get("text", "")
            if re.search(r'\*bleep\*|\[bleep\]|\(bleep\)', text, re.IGNORECASE):
                defects.append({
                    "type": "PROFANITY_FORMAT",
                    "severity": "warning",
                    "line_id": sub.get("id"),
                    "description": "Bleep placeholder found. Platform requires asterisks (****) for beeped profanity.",
                    "suggestion": "Replace *bleep* or [bleep] with **** (count asterisks to match letter count)",
                    "text": text
                })

    # 3. Translator credit check — info only (subtitler task)
    if "translator credit:" in rules_text:
        found = any("translated by" in (s.get("text", "") or "").lower() for s in subtitles)
        if not found:
            defects.append({
                "type": "TRANSLATOR_CREDIT_REMINDER",
                "severity": "info",
                "line_id": subtitles[-1].get("id") if subtitles else None,
                "description": "Reminder: Platform requires 'Translated by [Name]' credit (2 seconds duration).",
                "suggestion": "Add 'Translated by [Name]' subtitle near end of file in GTS Pro."
            })

    # 4. First subtitle cue time — only check when timecodes are actually present
    if "first 1 second" in rules_text:
        # Find first non-zero subtitle with a timecode
        for sub in subtitles:
            if _is_zero_subtitle(sub.get("text", "")):
                continue
            start = sub.get("start_time", "")
            if not start:
                break  # no timecodes — skip this check
            sec = _tc_to_seconds(start)
            if sec is not None and sec < 1.0:
                defects.append({
                    "type": "CUED_TOO_EARLY",
                    "severity": "warning",
                    "line_id": sub.get("id"),
                    "description": f"First subtitle starts at {start} which is within the first 1 second of the programme. Platform disallows this.",
                    "suggestion": "Delay the start time of the first subtitle to after 1 second.",
                    "text": sub.get("text", "")
                })
            break  # only check the first non-zero sub

    # 5. Subtitler-only rules — things that can only be done in GTS Pro, not in the script
    #    These are reminders shown as INFO notes, never blocking errors.
    subtitler_reminders = []
    if "raise subtitle" in rules_text or "raise to top" in rules_text:
        subtitler_reminders.append("Raising subtitles: position subtitles above on-screen text/graphics or to top when covering speaker's mouth (done in GTS Pro).")
    if "centre-justified" in rules_text or "center-justified" in rules_text:
        subtitler_reminders.append("Positioning: subtitles must be centre-justified at bottom (set in GTS Pro profile — not a script change).")
    if "file_naming_format" not in platform and "file naming" in rules_text:
        subtitler_reminders.append("File naming: ensure the exported PAC file follows the required naming convention before delivery.")
    if "zero subtitle" in rules_text or "zero_subtitle_required" in str(platform):
        subtitler_reminders.append("Zero subtitle: ensure subtitle #0 (00:00:00:00) contains Show name, STORY: [ID], LANG: ENG.")
    if "repo file" in rules_text or "repositioning" in rules_text:
        subtitler_reminders.append("Create a repo file for repositioning (done in GTS Pro after timing is complete).")
    if "end credit file" in rules_text:
        subtitler_reminders.append("Create a separate end credit file for repositioned credits (GTS Pro task).")
    if "spellcheck" in rules_text:
        subtitler_reminders.append("Always run spellcheck before delivery (GTS Pro > Tools > Spellcheck).")

    if subtitler_reminders:
        defects.append({
            "type": "SUBTITLER_REMINDERS",
            "severity": "info",
            "line_id": None,
            "description": "Subtitler-only tasks (cannot be checked automatically): " + " | ".join(subtitler_reminders),
            "suggestion": "Complete these tasks in GTS Pro before final delivery."
        })

    return defects
