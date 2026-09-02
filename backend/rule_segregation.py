# rule_segregation.py — Classify extracted guideline rules and route them to the
# correct processing stage of the cleaning pipeline.
#
# WHY THIS EXISTS
# ----------------
# Our tool does MORE than script/Text cleaning. Beyond the dialogue text, it also
# performs the SUBTITLER-OPERATIONAL work that other tools push onto a human in
# GTS Pro / Swift / EZCap. Specifically, the operational engine
# (`timecoded_subtitles.prepare_for_platform` + `_repair_timing_windows` +
# `_ensure_zero_subtitle` + `_split_long_subtitles`) deterministically:
#
#   * adjusts each subtitle's TIMECODES to satisfy reading-speed / CPS limits,
#   * enforces minimum / maximum DURATION windows per subtitle,
#   * enforces the minimum GAP (frame interval) between consecutive subtitles,
#   * inserts the ZERO-SUBTITLE field (STORY:/LANG:) when the platform requires it,
#   * splits long dialogue across lines within the MAX LINES / MAX CHARS limits.
#
# So operational rules are NOT "human-only". They are machine-applied. The job of
# this module is to SEGREGATE every extracted rule at extraction time into one of
# four buckets and, crucially, to translate timing/reading-speed/duration/zero-
# subtitle rules into the numeric platform fields the engine understands — instead
# of dumping them into a "subtitler_rules" list that nothing consumes.
#
# BUCKETS
# -------
#   text        -> dialogue text changes (handled by LLM cleaner + auto_fix)
#   timing      -> CPS / reading-speed / duration / gap / zero-subtitle
#                  -> converted into platform operational fields (code engine)
#   positioning  -> top/bottom/centre justification, overlap, raise/lower
#                  -> stored as delivery metadata + surfaced as a checklist note
#   file        -> file format / naming / credits / font -> delivery metadata notes
#
# The `text` and `timing` buckets are what the machine ACTS on. `positioning` and
# `file` are recorded as human-facing delivery notes (they still require a human in
# the NLE/GTS Pro for true placement, but we capture them so nothing is lost).

import re

# ─── CATEGORY KEYWORDS ─────────────────────────────────────────────────────────

# Phrases that prove a rule is a DIALOGUE-TEXT rule (stays in `text` bucket).
# NOTE: "reading speed", "cps", "characters per second" are intentionally NOT here —
# they also appear in _TIMING_KEYWORDS, and timing wins in classify_rule().
# Keeping them here too caused ambiguity; timing/CPS belongs in the timing bucket.
_TEXT_PHRASES = [
    "character", "line", "subtitle", "dialogue", "word", "punctuation",
    "capital", "case", "spell", "profanity", "italic", "hyphen", "speaker",
    "acronym", "ellipsis", "quotation", "apostrophe", "number", "digit",
    "symbol", "ampersand", "remove", "strip", "hoh", "emt", "music", "laughter",
    "stage direction", "filler", "slang", "foreign", "song lyric", "voice",
    "max char", "maximum character", "characters per line", "max line",
    "maximum line", "line length", "line limit",
]

# Indicators that a rule is about TIMECODE / TIMING / READING-SPEED engineering.
_TIMING_KEYWORDS = [
    "reading speed", "cps", "characters per second", "characters/second",
    "reading rate", "reading velocity", "words per minute", "reading time",
    "duration", "minimum duration", "maximum duration", "min duration",
    "max duration", "too long on screen", "hold",
    "gap", "frame gap", "minimum gap", "2 frame", "two frame", "3 frame",
    "frame interval", "interval", "timecode", "time code", "frame rate",
    "fps", "frame header", "frame tail", "cue in", "cue out", "spotting",
    "shot change", "sync", "offset", "delay",
    "zero subtitle", "zero-subtitle", "zero sub", "story:", "lang:",
    "speed setting", "reading speed setting",
]

# Indicators for POSITIONING / PLACEMENT tasks.
_POSITIONING_KEYWORDS = [
    "positioning", "position subtitles", "raise subtitle", "lower subtitle",
    "centre-justified", "center-justified", "centre justified", "center justified",
    "bottom of screen", "top of screen", "overlap", "reposition", "repo file",
    "vertical position", "placement", "safe area", "safe area",
]

# Indicators for FILE / FONT / DELIVERY / CREDIT tasks.
_FILE_KEYWORDS = [
    "font size", "font colour", "font color", "font type", "font face",
    "file naming", "file name", "file format", "delivery", "deliverable",
    "export", "spellcheck", "spell check", "end credit", "translator credit",
    "translated by", "subtitling by", "caption editor", "caption studio",
    "swift", "ezcap", "pac file", "naming convention",
]

_TIMING_RE = re.compile(
    r"\b(reading speed|cps|characters? per second|duration|gap|frame gap|"
    r"frame interval|timecode|time code|frame rate|fps|frame header|frame tail|"
    r"cue[- ]?in|cue[- ]?out|spotting|shot change|sync|offset|delay|"
    r"zero[- ]?subtitle|story:|lang:|reading speed setting)\b",
    re.IGNORECASE,
)

_POSITIONING_RE = re.compile(
    r"\b(positioning|position subtitles|raise|lower|centre|center|"
    r"bottom of screen|top of screen|overlap|reposition|placement|safe area)\b",
    re.IGNORECASE,
)

_FILE_RE = re.compile(
    r"\b(font|file naming|file name|file format|delivery|deliverable|export|"
    r"spellcheck|spell check|end credit|translator credit|translated by|"
    r"subtitling by|caption editor|caption studio|swift|ezcap|pac file|"
    r"naming convention)\b",
    re.IGNORECASE,
)


def classify_rule(rule: str) -> str:
    """Return one of: 'text', 'timing', 'positioning', 'file'."""
    r = (rule or "").lower()

    # A "text" phrase hit always wins for the text bucket UNLESS the rule is
    # clearly a timing/duration constraint expressed as a reading-speed limit.
    is_text = any(p in r for p in _TEXT_PHRASES)
    is_timing_kw = any(kw in r for kw in _TIMING_KEYWORDS) or bool(_TIMING_RE.search(r))
    is_positioning = any(kw in r for kw in _POSITIONING_KEYWORDS) or bool(_POSITIONING_RE.search(r))
    is_file = any(kw in r for kw in _FILE_KEYWORDS) or bool(_FILE_RE.search(r))

    # Reading-speed / CPS / duration / gap / zero-subtitle rules are TIMING even
    # though they mention "characters" or "reading speed" (text phrases) — they
    # drive the timecode engine, not the dialogue text.
    if is_timing_kw:
        # But a pure spelling/case rule that merely says "characters per line"
        # is a line-length (text/splitting) rule, not a timecode rule.
        if "characters per line" in r or "max char" in r or "line length" in r or "max line" in r:
            return "text"
        return "timing"

    if is_positioning:
        return "positioning"
    if is_file:
        return "file"
    if is_text:
        return "text"
    # Default: if it mentions seconds/frames but nothing else, treat as timing.
    if re.search(r"\b(\d+\s*(?:seconds|frames|secs|s)|frame|second)\b", r):
        return "timing"
    return "text"


# ─── NUMERIC FIELD PARSING (timing -> platform operational fields) ─────────────
# These populate the exact fields consumed by prepare_for_platform().

_NUM = r"(\d+(?:\.\d+)?)"

_DURATION_MIN_RE = re.compile(
    rf"minimum\s*duration[^\d]{{0,40}}?{_NUM}\s*(?:seconds|secs|s)\b", re.IGNORECASE)
_DURATION_MAX_RE = re.compile(
    rf"maximum\s*duration[^\d]{{0,40}}?{_NUM}\s*(?:seconds|secs|s)\b", re.IGNORECASE)
_CPS_MAX_RE = re.compile(
    rf"(?:reading speed|maximum|max)?[^\d]{{0,30}}?{_NUM}\s*(?:cps|characters per second)\b", re.IGNORECASE)
_GAP_FRAME_RE = re.compile(
    rf"(?:minimum\s*gap|gap\s*of|a\s+)?[^\d]{{0,40}}?{_NUM}\s*-?\s*frames?(?:\s*gap)?\b", re.IGNORECASE)
_GAP_SEC_RE = re.compile(
    rf"(?:minimum\s*gap|gap\s*of|a\s+)?[^\d]{{0,40}}?{_NUM}\s*(?:seconds|secs|s)\b", re.IGNORECASE)
_ZERO_SUB_RE = re.compile(r"zero[- ]?subtitle|story:\s*\w|lang:\s*\w", re.IGNORECASE)


def derive_timing_fields(rules: list[str], base: dict | None = None, fps: float = 25.0) -> dict:
    """
    Given the list of TIMING-bucket rules, derive the numeric operational fields
    the code engine needs. Returns a dict of platform field overrides. Values not
    mentioned by the rules keep the `base` (platform default) value.
    """
    fields = dict(base or {})
    changed = {}

    for rule in rules:
        # Minimum duration
        m = _DURATION_MIN_RE.search(rule)
        if m:
            val = float(m.group(1))
            if val > 0:
                fields["min_duration_seconds"] = val
                changed["min_duration_seconds"] = val
        # Maximum duration
        m = _DURATION_MAX_RE.search(rule)
        if m:
            val = float(m.group(1))
            if val > 0:
                fields["max_duration_seconds"] = val
                changed["max_duration_seconds"] = val
        # CPS / reading speed max
        m = _CPS_MAX_RE.search(rule)
        if m:
            val = float(m.group(1))
            if val > 0:
                fields["reading_speed_max_cps"] = val
                changed["reading_speed_max_cps"] = val
        # Minimum gap in frames
        m = _GAP_FRAME_RE.search(rule)
        if m:
            frames = float(m.group(1))
            if frames > 0:
                secs = round(frames / float(fps or 25.0), 4)
                fields["min_interval_seconds"] = secs
                changed["min_interval_seconds"] = secs
        # Minimum gap in seconds
        m = _GAP_SEC_RE.search(rule)
        if m:
            val = float(m.group(1))
            if val > 0:
                fields["min_interval_seconds"] = val
                changed["min_interval_seconds"] = val
        # Zero-subtitle requirement
        if _ZERO_SUB_RE.search(rule):
            fields["zero_subtitle_required"] = True
            changed["zero_subtitle_required"] = True

    return fields, changed


# ─── TOP-LEVEL SEGREGATION ─────────────────────────────────────────────────────

def segregate_rules(script_rules: list[str], subtitler_rules: list[str]) -> dict:
    """
    Take the two rule lists the LLM extractor returns and re-segregate them by
    actual processing stage. Returns:
        {
          "text": [...],          # dialogue text rules (LLM + auto_fix)
          "timing": [...],        # CPS/duration/gap/zero-subtitle (code engine)
          "positioning": [...],   # placement notes (human checklist)
          "file": [...],          # font/file/credit notes (human checklist)
        }
    Text + timing are what the machine acts on; positioning + file are captured
    as delivery notes so nothing is silently dropped.
    """
    buckets = {"text": [], "timing": [], "positioning": [], "file": []}
    seen = set()

    def _add(cat, rule):
        key = (cat, rule.strip().lower())
        if not rule.strip() or key in seen:
            return
        seen.add(key)
        buckets[cat].append(rule.strip())

    # The old "subtitler_rules" list mixed timing + positioning + file. Split it.
    for rule in (subtitler_rules or []):
        cat = classify_rule(rule)
        _add(cat, rule)

    # Script rules are predominantly text, but re-classify to catch any that are
    # actually timing constraints mislabeled by the extractor.
    for rule in (script_rules or []):
        cat = classify_rule(rule)
        _add(cat, rule)

    return buckets
