# quality_checker.py — Checks cleaned subtitle files for OTT defects
# Based on real rules from OTT Clients Protocol Excel
# Covers: file naming, zero subtitle, char limits, timing, profanity, spacing, punctuation

import re
from platform_rules import get_platform, UNIVERSAL_GUIDELINES, get_profanity_table


def check_quality(subtitles: list, platform_key: str, filename: str) -> dict:
    """
    Run all quality checks on a cleaned subtitle list.
    Returns list of defects with line number, type, and description.
    """
    platform = get_platform(platform_key)
    defects = []

    # Run all checks
    defects += check_file_naming(filename, platform)
    defects += check_zero_subtitle(subtitles, platform)
    defects += check_each_line(subtitles, platform)
    defects += check_profanity(subtitles, platform_key)
    defects += check_spacing_punctuation(subtitles)
    defects += check_hoh_emt(subtitles, platform)

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
    """Check if file is named correctly per platform rules"""
    defects = []
    naming_format = platform.get("file_naming_format", "")

    if not naming_format:
        return defects

    # Guide Discovery / Discovery: EHD_123456E_ENG.PAC
    if "EHD_" in naming_format:
        pattern = r'^EHD_\d{6}[A-Z]_[A-Z]{3}\.PAC$'
        if not re.match(pattern, filename, re.IGNORECASE):
            defects.append({
                "type": "FILE_NAMING",
                "severity": "critical",
                "line_id": None,
                "description": f"File name '{filename}' does not match required format '{naming_format}'. Wrong file name = automatic rejection by OTT platform.",
                "suggestion": f"Rename to format: {naming_format}"
            })

    return defects


def check_zero_subtitle(subtitles: list, platform: dict) -> list:
    """Check if zero subtitle exists and is correctly formatted"""
    defects = []

    if not platform.get("zero_subtitle_required", False):
        return defects

    if not subtitles:
        defects.append({
            "type": "ZERO_SUBTITLE_MISSING",
            "severity": "critical",
            "line_id": None,
            "description": "File has no subtitles at all. Zero subtitle is required.",
            "suggestion": "Add zero subtitle at timecode 00:00:00:00 to 00:00:00:08 with show name, episode, language, STORY: and LANG: fields."
        })
        return defects

    first = subtitles[0]
    text = first.get("text", "")

    # Check if first subtitle looks like a zero subtitle
    # Zero subtitle should have STORY: and LANG: fields
    has_story = "STORY:" in text.upper()
    has_lang = "LANG:" in text.upper()

    if not has_story or not has_lang:
        defects.append({
            "type": "ZERO_SUBTITLE_INVALID",
            "severity": "critical",
            "line_id": first.get("id"),
            "description": f"First subtitle does not appear to be a valid zero subtitle. Missing STORY: and/or LANG: fields. Any mistake in zero subtitle = file fails to transmit.",
            "suggestion": "Zero subtitle must contain: Show name, Episode, Language, STORY: [programme ID], LANG: ENG"
        })

    # Check zero subtitle timecode
    start = first.get("start_time", "")
    if start and start not in ["00:00:00,000", "00:00:00:00", ""]:
        defects.append({
            "type": "ZERO_SUBTITLE_TIMING",
            "severity": "critical",
            "line_id": first.get("id"),
            "description": f"Zero subtitle start time should be 00:00:00:00, found: {start}",
            "suggestion": "Set zero subtitle timecode in to 00:00:00:00 and out to 00:00:00:08 (8 frames)"
        })

    return defects


def check_each_line(subtitles: list, platform: dict) -> list:
    """Check every subtitle line against platform rules"""
    defects = []
    max_chars = platform.get("max_chars_per_line", 42)
    max_chars_italics = platform.get("max_chars_italics", max_chars)
    max_lines = platform.get("max_lines", 2)
    max_duration = platform.get("max_duration_seconds", 7.0)
    min_duration = platform.get("min_duration_seconds", 1.0)
    max_cps = platform.get("reading_speed_max_cps", 21)

    for sub in subtitles:
        sub_id = sub.get("id")
        text = sub.get("text", "")
        lines = text.split("\n")

        # Check number of lines
        if len(lines) > max_lines:
            defects.append({
                "type": "TOO_MANY_LINES",
                "severity": "error",
                "line_id": sub_id,
                "description": f"Subtitle has {len(lines)} lines. Maximum is {max_lines}.",
                "suggestion": f"Split into multiple subtitles or rewrite to fit in {max_lines} lines.",
                "text": text
            })

        # Check chars per line
        for i, line in enumerate(lines):
            line_clean = re.sub(r'<[^>]+>', '', line)  # strip HTML tags
            if len(line_clean) > max_chars:
                defects.append({
                    "type": "LINE_TOO_LONG",
                    "severity": "error",
                    "line_id": sub_id,
                    "description": f"Line {i+1} is {len(line_clean)} characters. Maximum for {platform['name']} is {max_chars}.",
                    "suggestion": f"Split at a natural phrase boundary to fit within {max_chars} characters.",
                    "text": text
                })

        # Check duration if timecodes available
        start = sub.get("start_time", "")
        end = sub.get("end_time", "")
        if start and end and start != "" and end != "":
            duration = parse_duration(start, end)
            if duration is not None:
                if duration < min_duration:
                    defects.append({
                        "type": "DURATION_TOO_SHORT",
                        "severity": "warning",
                        "line_id": sub_id,
                        "description": f"Subtitle duration is {duration:.2f}s. Minimum for {platform['name']} is {min_duration}s.",
                        "suggestion": "Extend the out-time to meet minimum duration requirement.",
                        "text": text
                    })
                if duration > max_duration:
                    defects.append({
                        "type": "DURATION_TOO_LONG",
                        "severity": "warning",
                        "line_id": sub_id,
                        "description": f"Subtitle duration is {duration:.2f}s. Maximum for {platform['name']} is {max_duration}s.",
                        "suggestion": "Split into multiple subtitles.",
                        "text": text
                    })

                # Check reading speed
                char_count = len(re.sub(r'\s+', '', text))
                if duration > 0:
                    cps = char_count / duration
                    if cps > max_cps:
                        defects.append({
                            "type": "READING_SPEED_TOO_HIGH",
                            "severity": "warning",
                            "line_id": sub_id,
                            "description": f"Reading speed is {cps:.1f} CPS. Maximum for {platform['name']} is {max_cps} CPS.",
                            "suggestion": "Shorten the subtitle text or extend the duration.",
                            "text": text
                        })

    return defects


def check_profanity(subtitles: list, platform_key: str) -> list:
    """Check for unhandled profanity that should be replaced per platform rules"""
    defects = []
    profanity_table = get_profanity_table(platform_key)

    if not profanity_table:
        return defects

    for sub in subtitles:
        text = sub.get("text", "").lower()
        for word, replacement in profanity_table.items():
            pattern = r'\b' + re.escape(word) + r'\b'
            if re.search(pattern, text, re.IGNORECASE):
                defects.append({
                    "type": "PROFANITY_NOT_REPLACED",
                    "severity": "error",
                    "line_id": sub.get("id"),
                    "description": f"Word '{word}' found. Must be replaced with '{replacement}' for {platform_key}.",
                    "suggestion": f"Replace '{word}' with '{replacement}'",
                    "text": sub.get("text", "")
                })

    return defects


def check_spacing_punctuation(subtitles: list) -> list:
    """Check common spacing and punctuation defects — these cause OTT rejections"""
    defects = []

    for sub in subtitles:
        sub_id = sub.get("id")
        text = sub.get("text", "")
        issues = []

        # Double space
        if "  " in text:
            issues.append("double space found")

        # Space before punctuation
        if re.search(r'\s[.,!?;:]', text):
            issues.append("space before punctuation mark")

        # Double punctuation
        if re.search(r'[.]{3,}', text) and not re.search(r'\.{3}$', text):
            issues.append("excessive dots (use exactly 3 for ellipsis)")
        if re.search(r'[!]{2,}', text):
            issues.append("double exclamation marks")
        if re.search(r'[?]{2,}', text):
            issues.append("double question marks")

        # Trailing space
        if text != text.strip():
            issues.append("leading or trailing space")

        # All caps (unless intentional)
        words = text.split()
        caps_words = [w for w in words if w.isupper() and len(w) > 2 and w.isalpha()]
        if len(caps_words) > 2:
            issues.append(f"multiple ALL CAPS words: {', '.join(caps_words[:3])}")

        # Starts with lowercase
        stripped = text.strip()
        if stripped and stripped[0].islower():
            issues.append("line starts with lowercase letter")

        if issues:
            defects.append({
                "type": "FORMATTING_DEFECT",
                "severity": "error",
                "line_id": sub_id,
                "description": f"Formatting issues: {'; '.join(issues)}",
                "suggestion": "Fix the formatting issues listed above",
                "text": text
            })

    return defects


def check_hoh_emt(subtitles: list, platform: dict) -> list:
    """Check for HOH and EMT elements that must be removed for Discovery/DMAX"""
    defects = []
    remove_elements = platform.get("remove_elements", [])

    if "HOH" not in remove_elements and "EMT" not in remove_elements:
        return defects

    # HOH patterns: [MUSIC], [APPLAUSE], [LAUGHTER], (sound effects)
    hoh_patterns = [
        r'\[MUSIC[^\]]*\]', r'\[APPLAUSE\]', r'\[LAUGHTER\]',
        r'\[CHEERING\]', r'\[GUNSHOT\]', r'\[EXPLOSION\]',
        r'\(narrator\)', r'\(narrating\)', r'\(whispering\)',
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
                    "description": f"HOH/EMT accessibility element found in subtitle. Must be removed for {platform['name']}.",
                    "suggestion": "Remove the HOH/EMT element completely from this subtitle.",
                    "text": text
                })
                break

    return defects


def parse_duration(start: str, end: str) -> float:
    """Parse two timecodes and return duration in seconds"""
    try:
        def to_seconds(tc):
            tc = tc.replace(',', '.').replace(';', ':')
            parts = tc.split(':')
            if len(parts) == 4:
                h, m, s, f = parts
                return int(h)*3600 + int(m)*60 + float(s) + int(f)/25
            elif len(parts) == 3:
                h, m, s = parts
                return int(h)*3600 + int(m)*60 + float(s)
            return 0.0

        return to_seconds(end) - to_seconds(start)
    except:
        return None
