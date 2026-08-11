import math

def frames_to_ms(frames: int, fps: float = 25.0) -> int:
    return int(math.floor(frames * 1000.0 / fps))

def format_time(h: int, m: int, s: int, ms: int) -> str:
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def get_timecode(buffer: bytes, index: int) -> str:
    if index < 0 or index + 3 >= len(buffer):
        return format_time(0, 0, 0, 0)

    val_high = buffer[index] + buffer[index + 1] * 256
    val_low = buffer[index + 2] + buffer[index + 3] * 256

    high_str = f"{val_high:06d}"
    low_str = f"{val_low:06d}"

    hours = int(high_str[0:4])
    minutes = int(high_str[4:6])
    seconds = int(low_str[2:4])
    frames = int(low_str[4:6])

    ms = frames_to_ms(frames)
    return format_time(hours, minutes, seconds, ms)


# Words that only ever appear in the PAC "story"/header block (Title, Episode,
# Client, No. of Subs, 1st Cue In, ...). Subtitle Edit stores this region in
# the file Header, never as subtitle paragraphs, so we must skip it.
_STORY_MARKERS = (
    "TITLE", "EPISODE", "CLIENT", "LAN", "NO. OF SUBS", "1ST CUE IN",
    "LAST CUE OUT", "FILE NAME", "VOD", "ASPECT", "STORY", "LANGUAGE",
    "PROGRAM", "SERIES", "TRANSLAT", "SUBTITL", "DISK", "DISC",
)


def _looks_like_story(text: str) -> bool:
    head = text.strip().upper()
    if not head:
        return False
    # The story block often carries a long run of lines; a single very long
    # text blob is never a real subtitle.
    if len(head) > 200:
        return True
    for marker in _STORY_MARKERS:
        if head.startswith(marker):
            return True
    return False


# Single-byte PAC special characters (quotes, dashes, symbols).
# Built with chr()+code points so the source stays pure ASCII.
_SPECIAL_BYTES = {
    0x1c: chr(0x201c), 0x1d: chr(0x201d), 0x18: chr(0x2018), 0x19: chr(0x2019),
    0x2d: "-", 0x5f: chr(0x2013), 0x13: chr(0x2013), 0x14: chr(0x2014),
    0x23: chr(0x00a3), 0x80: "#", 0x81: chr(0x00df), 0x7c: chr(0x00e6),
    0x7d: chr(0x00f8), 0x7e: chr(0x00a7), 0x5c: chr(0x00c6), 0x5d: chr(0x00d8),
    0x5e: chr(0x00f7),     0x8a: chr(0x00ab), 0x8b: chr(0x00bb), 0x09: " ",
    0x83: chr(0x00b3), 0x82: chr(0x00b2), 0x85: chr(0x00f8),
    0xa8: chr(0x00bf), 0xa9: chr(0x00a1), 0xa6: chr(0x00aa), 0xa7: chr(0x00ba),
}

# Accented glyphs are stored as a 0xE0-0xE9 prefix byte followed by the base
# (ASCII) letter, e.g. 0xE2 0x61 -> 'a' with acute.  Code points only.
_ACCENT_TABLE = {
    0xe2: {"a": 0x00e1, "e": 0x00e9, "i": 0x00ed, "o": 0x00f3, "u": 0x00fa,
           "y": 0x00fd, "A": 0x00c1, "E": 0x00c9, "I": 0x00cd, "O": 0x00d3,
           "U": 0x00da, "Y": 0x00dd},
    0xe3: {"a": 0x00e0, "e": 0x00e8, "i": 0x00ec, "o": 0x00f2, "u": 0x00f9,
           "A": 0x00c0, "E": 0x00c8, "I": 0x00cc, "O": 0x00d2, "U": 0x00d9},
    0xe4: {"a": 0x00e2, "e": 0x00ea, "i": 0x00ee, "o": 0x00f4, "u": 0x00fb,
           "A": 0x00c2, "E": 0x00ca, "I": 0x00ce, "O": 0x00d4, "U": 0x00db},
    0xe5: {"a": 0x00e4, "e": 0x00eb, "i": 0x00ef, "o": 0x00f6, "u": 0x00fc,
           "y": 0x00ff, "A": 0x00c4, "E": 0x00cb, "I": 0x00cf, "O": 0x00d6,
           "U": 0x00dc, "Y": 0x0178},
    0xe6: {"a": 0x00e3, "n": 0x00f1, "o": 0x00f5, "A": 0x00c3, "N": 0x00d1,
           "O": 0x00d5},
    0xe8: {"c": 0x00e7, "C": 0x00c7},
}


def _accent_char(prefix: int, base: str):
    cp = _ACCENT_TABLE.get(prefix, {}).get(base)
    return chr(cp) if cp else None


def _decode_pac_text(buffer: bytes, start: int, end: int) -> str:
    """Decode a PAC text region using the Latin codepage rules."""
    parts = []
    buf = bytearray()

    def flush():
        if buf:
            parts.append(buf.decode("cp1252", errors="replace"))
            buf.clear()

    curr = start
    while curr <= end and curr < len(buffer):
        b = buffer[curr]

        if b == 0x1f and curr + 4 <= len(buffer) and buffer[curr:curr + 4] == b"\x1fW16":
            curr += 5
            continue
        if b == 0x1f and curr + 4 <= len(buffer) and buffer[curr:curr + 4] == b"\x1f\xef\xbb\xbf":
            curr += 4
            continue
        if b == 0xFE:
            flush()
            parts.append("\n")
            curr += 2
            continue
        if b == 0xFF:
            flush()
            parts.append(" ")
            curr += 1
            continue
        if b == 0x00:
            break
        # Inline control bytes (tab, color, position, etc.) carry no glyph.
        if 0x00 < b < 0x08 or b in (0x0b, 0x0d, 0x17, 0x1d):
            curr += 1
            continue
        # Accent composite: 0xE0-0xE9 prefix + base letter.
        if 0xe0 <= b <= 0xe9 and curr + 1 < len(buffer):
            nxt = buffer[curr + 1]
            if 0x41 <= nxt <= 0x7a:
                ch = _accent_char(b, chr(nxt))
                if ch:
                    flush()
                    parts.append(ch)
                    curr += 2
                    continue
        if b in _SPECIAL_BYTES:
            flush()
            parts.append(_SPECIAL_BYTES[b])
            curr += 1
            continue

        buf.append(b)
        curr += 1

    flush()
    return "".join(parts).replace("\x00", "").strip()


def read_pac(file_bytes: bytes) -> str:
    if not file_bytes or len(file_bytes) < 20:
        return ""

    paragraphs = []
    index = 0
    seen_time_starts = set()

    # Track timing of the last *accepted* subtitle so we can reject the PAC
    # story block and corrupt/duplicate records the way Subtitle Edit does
    # (consecutive subtitles must start/end within 1..1500 s of each other).
    last_start = -1.0
    last_end = -1.0
    accepted_count = 0

    while index < len(file_bytes):
        # Find the next PAC item header: a 0xFE whose 15th or 12th preceding
        # byte is the timing marker (0x60..0x67).
        index += 1
        if index + 20 >= len(file_bytes):
            break

        if file_bytes[index] != 0xFE:
            continue

        minus15 = file_bytes[index - 15]
        minus12 = file_bytes[index - 12]
        time_start_index = -1
        if 0x60 <= minus15 <= 0x67:
            time_start_index = index - 15
        elif 0x60 <= minus12 <= 0x67:
            time_start_index = index - 12

        if time_start_index < 0:
            continue

        # A corrupt/overlong header can resurface; read each header once.
        if time_start_index in seen_time_starts:
            index = max(index, time_start_index + 11)
            continue
        seen_time_starts.add(time_start_index)

        fe_index = index
        alignment = file_bytes[fe_index + 1]
        # bit 0-1 = horizontal alignment, bit 2 (0x04) = italic flag
        italic = bool(alignment & 0x04)
        alignment &= 0x03

        # Resolve the real start of the timing header (some records pad 3 bytes).
        if file_bytes[time_start_index] == 0x60:
            pass
        elif 0x61 <= file_bytes[time_start_index] <= 0x67:
            pass
        elif file_bytes[time_start_index + 3] == 0x60:
            time_start_index += 3
        elif 0x61 <= file_bytes[time_start_index + 3] <= 0x67:
            time_start_index += 3
        else:
            index = time_start_index + 11
            continue

        start_time = get_timecode(file_bytes, time_start_index + 1)
        end_time = get_timecode(file_bytes, time_start_index + 5)

        text_len = file_bytes[time_start_index + 9] + file_bytes[time_start_index + 10] * 256
        # Hard guard: real subtitle text is never this long.  This also kills
        # the PAC story block, whose "text length" field is meaningless.
        if text_len < 1 or text_len > 500:
            index = time_start_index + 11
            continue

        # For the 0x61..0x67 (non-primary) timing variant, Subtitle Edit also
        # requires the declared length to be sane and the cue to fall within a
        # believable gap of the previous subtitle.
        header_byte = file_bytes[time_start_index]
        secondary_timing = 0x61 <= header_byte <= 0x67
        if secondary_timing:
            if text_len > 200:
                index = time_start_index + 11
                continue
            if accepted_count > 0:
                cur_start = _tc_seconds(start_time)
                cur_end = _tc_seconds(end_time)
                if cur_start is None or cur_end is None:
                    index = time_start_index + 11
                    continue
                gap_start = cur_start - last_start
                gap_end = cur_end - last_end
                if not (1 <= gap_start <= 1500) or not (1 <= gap_end <= 1500):
                    index = time_start_index + 11
                    continue

        max_index = min(time_start_index + 10 + text_len, len(file_bytes) - 1)

        # Decode the text region using the PAC Latin codepage (accents +
        # special characters), stopping at the declared length.
        text_str = _decode_pac_text(file_bytes, fe_index + 3, max_index)

        # Keep every genuine (timecoded) record — including the PAC "story"
        # header block, which Subtitle Edit exposes as paragraph #1 (e.g. at
        # 00:00:00,323).  Dropping it would make our cue count fall short of
        # Subtitle Edit's, so we preserve it 1:1.
        if not text_str:
            index = max(index, max_index)
            continue

        if italic and "<i>" not in text_str:
            text_str = f"<i>{text_str}</i>"

        if alignment == 1:
            text_str = r"{\an7}" + text_str
        elif alignment == 0:
            text_str = r"{\an9}" + text_str

        paragraphs.append({"start": start_time, "end": end_time, "text": text_str})

        last_start = _tc_seconds(start_time) or last_start
        last_end = _tc_seconds(end_time) or last_end
        accepted_count += 1

        # Skip past this item so the inner line-break 0xFE markers inside its
        # text are never mistaken for a new header (the source of spurious cues).
        index = max(index, max_index)

    srt_out = []
    for i, p in enumerate(paragraphs, 1):
        srt_out.append(str(i))
        srt_out.append(f"{p['start']} --> {p['end']}")
        srt_out.append(p["text"])
        srt_out.append("")

    return "\n".join(srt_out)


def _tc_seconds(tc: str):
    try:
        h, m, rest = tc.split(":")
        s, ms = rest.split(",")
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0
    except Exception:
        return None
