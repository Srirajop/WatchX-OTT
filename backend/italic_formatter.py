# italic_formatter.py — Apply italics per OTT platform rules
# Platforms define when italics are required:
# - Disney: narration/VO, phone calls, foreign terms, radio/TV/off-screen sound, singing
# - Discovery/DMAX/Guide: song lyrics in italics, foreign words not in common English
# - Nickelodeon: NO italics for songs/VO/phone/TV/radio/narrator
# - TVB: NO italics for songs
# - Generic: singing in italics

import re

# Platform-level italics rules (what contexts get italics)
_PLATFORM_ITALICS_RULES: dict[str, dict] = {
    "disney": {
        "singing": True,
        "narration_vo": True,
        "phone_calls": True,
        "foreign_terms": True,
        "off_screen_sound": True,
        "song_lyrics": True,
    },
    "discovery_max": {
        "singing": False,
        "song_lyrics": True,
        "foreign_terms": True,
        "narration_vo": False,
    },
    "dmax": {
        "singing": False,
        "song_lyrics": True,
        "foreign_terms": True,
        "narration_vo": False,
    },
    "guide_discovery": {
        "singing": False,
        "song_lyrics": True,
        "foreign_terms": True,
        "narration_vo": False,
    },
    "discovery_scripps": {
        # No text styles in EN2 files
        "singing": False,
        "song_lyrics": False,
        "foreign_terms": False,
        "narration_vo": False,
        "no_italics": True,
    },
    "nickelodeon": {
        # No italics for songs/VO/phone/TV/radio/narrator
        "no_italics": True,
    },
    "tvb": {
        # No italics for songs
        "no_italics": True,
    },
    "vubiquity": {
        "singing": False,
        "song_lyrics": False,
        "foreign_terms": False,
        "narration_vo": False,
    },
    "generic": {
        "singing": True,
        "song_lyrics": True,
        "foreign_terms": False,
        "narration_vo": True,
    },
}

# Music note symbols that indicate a song line
_MUSIC_NOTE_RE = re.compile(r"[♪♫🎵🎶]")

# Common foreign words (that SHOULD be italicised per Iyuno guidelines)
_FOREIGN_WORDS = {
    "voilà", "voila", "c'est la vie", "je ne sais quoi", "merci",
    "oui", "non", "mon dieu", "merde", "sacré bleu",
    "gracias", "por favor", "sí", "señor", "señora",
    "ciao", "prego", "mamma mia", "arrivederci",
    "danke", "bitte", "ja", "nein",
    "arigato", "konnichiwa", "sayonara",
    "namaste", "karma", "nirvana", "yoga",
    "schadenfreude", "zeitgeist", "angst",
    "faux pas", "déjà vu", "rendezvous", "fiancé", "fiancée",
    "cafe", "café", "naïve", "résumé", "façade",
}

# Narration markers
_NARRATION_RE = re.compile(
    r"\b(narrator|narrating|narration|voiceover|voice.?over|v\.o\.)\b",
    re.IGNORECASE,
)

# Phone/radio/TV in-text markers
_PHONE_RE = re.compile(
    r"\b(over the phone|via phone|on the phone|over intercom|over radio|on the radio|"
    r"on tv|on television|on the news|over speaker|loudspeaker)\b",
    re.IGNORECASE,
)


def _wrap_italic(text: str) -> str:
    """Wrap text in SRT italic tags, skip if already wrapped."""
    text = text.strip()
    if text.startswith("<i>") and text.endswith("</i>"):
        return text
    return f"<i>{text}</i>"


def _is_song_line(text: str) -> bool:
    """Check if a subtitle line looks like a song/lyric."""
    return bool(_MUSIC_NOTE_RE.search(text))


def _contains_foreign_word(text: str) -> bool:
    lower = text.lower()
    return any(fw in lower for fw in _FOREIGN_WORDS)


def _is_narrator_line(metadata: dict) -> bool:
    """Check if the subtitle was flagged as narrator/VO in metadata."""
    return metadata.get("is_narration", False) or metadata.get("is_vo", False)


def apply_italics_rules(subtitles: list[dict], platform_key: str) -> list[dict]:
    """
    Apply italics formatting to subtitle text based on platform rules.
    
    This transforms:
    - Song lyrics (♪ lines) → wrapped in <i>...</i> for platforms that require it
    - Narration/VO lines → <i>...</i> where required
    - Foreign word snippets → inline <i>word</i> tags where required
    - Strips all italics for platforms that forbid them (Nickelodeon, TVB, Discovery Scripps)
    """
    # Get platform rules — default to generic
    key = platform_key.lower()
    rules = None
    for p_key in _PLATFORM_ITALICS_RULES:
        if p_key in key:
            rules = _PLATFORM_ITALICS_RULES[p_key]
            break
    if rules is None:
        rules = _PLATFORM_ITALICS_RULES.get("generic", {})

    # If platform explicitly forbids ALL italics, strip any existing italic tags
    if rules.get("no_italics"):
        out = []
        for sub in subtitles:
            before = sub.get("text", "")
            item = _strip_italics(sub)
            hints = list(sub.get("rule_hints", []))
            if "<i>" in before and "<i>" not in item.get("text", ""):
                if "italics_removed" not in hints:
                    hints.append("italics_removed")
                item["rule_hints"] = hints
            out.append(item)
        return out

    result = []
    for sub in subtitles:
        text = sub.get("text", "")
        if not text:
            result.append(sub)
            continue

        item = dict(sub)
        lines = text.split("\n")
        processed_lines = []

        for line in lines:
            line_result = line

            # 1. Song lyrics — wrap whole line in italics
            if _is_song_line(line):
                if rules.get("song_lyrics") or rules.get("singing"):
                    line_result = _wrap_italic(line)
                # else: keep as-is (Nickelodeon etc — already handled by no_italics)

            # 2. Foreign words — inline italics for the specific word/phrase
            elif rules.get("foreign_terms") and _contains_foreign_word(line):
                line_result = _italicize_foreign_words(line)

            processed_lines.append(line_result)

        item["text"] = "\n".join(processed_lines)

        # Record exactly which italics operation actually happened, so the
        # track-changes audit trail is truthful.
        hints = list(sub.get("rule_hints", []))
        if "<i>" in item["text"] and "<i>" not in text:
            if "italics_added" not in hints:
                hints.append("italics_added")
        if "<i>" in text and "<i>" not in item["text"]:
            if "italics_removed" not in hints:
                hints.append("italics_removed")
        item["rule_hints"] = hints

        result.append(item)

    return result


def _strip_italics(sub: dict) -> dict:
    """Remove all <i>...</i> tags from subtitle text."""
    item = dict(sub)
    text = item.get("text", "")
    text = re.sub(r"</?i>", "", text)
    item["text"] = text
    return item


def _italicize_foreign_words(text: str) -> str:
    """Wrap known foreign words with <i>...</i> tags inline."""
    # Sort by length descending to match multi-word phrases first
    for fw in sorted(_FOREIGN_WORDS, key=len, reverse=True):
        pattern = re.compile(re.escape(fw), re.IGNORECASE)
        # Only replace if not already inside italics
        def replace_match(m):
            start = m.start()
            # Check if already within <i>...</i>
            before = text[:start]
            open_tags = before.count("<i>")
            close_tags = before.count("</i>")
            if open_tags > close_tags:
                return m.group()  # already in italics
            return f"<i>{m.group()}</i>"
        text = pattern.sub(replace_match, text)
    return text


def has_italics_errors(subtitles: list[dict], platform_key: str) -> list[dict]:
    """
    Check for italics formatting errors.
    Returns a list of defect dicts for lines that violate platform italics rules.
    """
    key = platform_key.lower()
    rules = None
    for p_key in _PLATFORM_ITALICS_RULES:
        if p_key in key:
            rules = _PLATFORM_ITALICS_RULES[p_key]
            break
    if rules is None:
        rules = _PLATFORM_ITALICS_RULES.get("generic", {})

    defects = []

    for sub in subtitles:
        text = sub.get("text", "")
        if not text:
            continue

        # Platform forbids italics but text has them
        if rules.get("no_italics") and ("<i>" in text or "</i>" in text):
            defects.append({
                "type": "ITALICS_NOT_ALLOWED",
                "severity": "error",
                "line_id": sub.get("id"),
                "description": f"Platform '{platform_key}' forbids italic text, but italic tags were found.",
                "suggestion": "Remove all <i>...</i> tags from this subtitle.",
                "text": text
            })

        # Song lyrics should be in italics but aren't
        if (rules.get("song_lyrics") or rules.get("singing")) and _is_song_line(text):
            if "<i>" not in text:
                defects.append({
                    "type": "SONG_LYRICS_NOT_ITALIC",
                    "severity": "warning",
                    "line_id": sub.get("id"),
                    "description": "Song/lyric line (♪) should be in italics for this platform.",
                    "suggestion": "Wrap the entire lyric line in <i>...</i> tags.",
                    "text": text
                })

    return defects
