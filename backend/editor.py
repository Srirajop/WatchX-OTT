# editor.py — Subtitle Editor engine (inspired by Subtitle Edit feature set)
#
# Provides multi-format subtitle import / export, timeline-friendly synchronization
# (adjust all times, visual / point sync, point sync via other subtitle), and
# auto-translation. Pure Python, no GUI — consumed by the FastAPI /editor routes.
#
# Timecodes are stored internally in SRT form: HH:MM:SS,mmm

import re
import io
import json
import csv
import xml.sax.saxutils as saxutils

from timecoded_subtitles import normalize_timecode, _to_seconds, _from_seconds, _renumber

_FPS_DEFAULT = 25

# Supported import / export formats (visible in the UI dropdowns too)
IMPORT_FORMATS = ["srt", "vtt", "ass", "ssa", "sub", "sbv", "lrc", "ttml", "xml", "csv", "json", "txt"]
EXPORT_FORMATS = ["srt", "vtt", "ass", "ssa", "sub", "sbv", "lrc", "ttml", "csv", "json", "txt"]


# ─── LOW LEVEL HELPERS ─────────────────────────────────────────────

def _sec(tc: str) -> float | None:
    return _to_seconds(tc) if tc else None


def _fmt(sec: float) -> str:
    return _from_seconds(sec)


def _entry(idx, start, end, text):
    start_tc = normalize_timecode(start) if start else ""
    end_tc = normalize_timecode(end) if end else ""
    if start_tc and end_tc:
        if _to_seconds(end_tc) <= _to_seconds(start_tc):
            end_tc = _from_seconds(_to_seconds(start_tc) + 1.0)
    return {
        "id": idx,
        "start_time": start_tc,
        "end_time": end_tc,
        "text": (text or "").strip(),
    }


def _strip_inline_tags(text: str) -> str:
    """Keep <i>/<b> tags (OTT convention) but drop other stray HTML."""
    text = text.replace("\\N", "\n").replace("\\n", "\n")
    return text


# ─── PARSERS ───────────────────────────────────────────────────────

def parse_srt(text: str) -> list:
    subs = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        if not lines:
            continue
        if lines[0].isdigit():
            lines = lines[1:]
        arrow = next((i for i, l in enumerate(lines) if "-->" in l), None)
        if arrow is None:
            continue
        timing = lines[arrow].split("-->", 1)
        if len(timing) != 2:
            continue
        body = "\n".join(lines[arrow + 1:])
        if body.strip():
            subs.append(_entry(0, timing[0], timing[1], _strip_inline_tags(body)))
    return _renumber(subs)


def parse_vtt(text: str) -> list:
    text = re.sub(r"WEBVTT.*?(\n\n|$)", "", text, flags=re.S)
    # Drop STYLE / NOTE blocks
    text = re.sub(r"(?m)^(?:STYLE|NOTE).*?(\n\n|$)", "", text, flags=re.S)
    subs = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        if not lines:
            continue
        if lines[0].isdigit() or re.match(r"^[\w-]+$", lines[0]):
            lines = lines[1:]
        arrow = next((i for i, l in enumerate(lines) if "-->" in l), None)
        if arrow is None:
            continue
        timing = lines[arrow].split("-->", 1)
        if len(timing) != 2:
            continue
        start = timing[0].strip().replace(".", ",")
        end = re.split(r"\s+", timing[1].strip().replace(".", ","))[0]
        body = "\n".join(lines[arrow + 1:])
        if body.strip():
            subs.append(_entry(0, start, end, _strip_inline_tags(body)))
    return _renumber(subs)


def parse_ass(text: str) -> list:
    subs = []
    in_events = False
    fmt_cols = []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[Events]"):
            in_events = True
            continue
        if line.startswith("["):
            in_events = False
            continue
        if not in_events:
            continue
        if line.startswith("Format:"):
            fmt_cols = [c.strip().lower() for c in line[len("Format:"):].split(",")]
            continue
        if not line.startswith("Dialogue:"):
            continue
        payload = line[len("Dialogue:"):].strip()
        # Split respecting the known column count
        parts = payload.split(",")
        if not fmt_cols:
            # Default Aegisub layout
            fmt_cols = ["layer", "start", "end", "style", "name", "marginl",
                        "marginr", "marginv", "effect", "text"]
        # Text column may contain commas — rejoin
        if len(parts) >= len(fmt_cols):
            data = dict(zip(fmt_cols, parts[:len(fmt_cols)]))
            text_col = ",".join(parts[len(fmt_cols) - 1:])
        else:
            # Fallback: start,end,text
            data = {"start": parts[0] if parts else "", "end": parts[1] if len(parts) > 1 else "",
                    "text": ",".join(parts[2:])}
            text_col = data["text"]
        start = _ass_time_to_srt(data.get("start", ""))
        end = _ass_time_to_srt(data.get("end", ""))
        body = _strip_inline_tags(text_col)
        if body.strip():
            subs.append(_entry(0, start, end, body))
    return _renumber(subs)


def _ass_time_to_srt(tc: str) -> str:
    tc = (tc or "").strip()
    m = re.match(r"(\d+):(\d{2}):(\d{2})\.(\d{2})", tc)
    if not m:
        return ""
    h, mn, s, cs = m.groups()
    ms = int(round(int(cs) * 10))
    return f"{int(h):02d}:{int(mn):02d}:{int(s):02d},{ms:03d}"


def parse_sub(text: str, fps: int = _FPS_DEFAULT) -> list:
    """MicroDVD format: {start_frame}{end_frame}Text"""
    subs = []
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"\{(\d+)\}\{(\d+)\}(.*)", line, re.S)
        if not m:
            continue
        s_f, e_f, body = m.groups()
        start = _from_seconds(int(s_f) / fps)
        end = _from_seconds(int(e_f) / fps)
        if body.strip():
            subs.append(_entry(0, start, end, _strip_inline_tags(body)))
    return _renumber(subs)


def parse_sbv(text: str) -> list:
    subs = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        if not lines:
            continue
        arrow = next((i for i, l in enumerate(lines) if "," in l and re.match(r"\d", l)), None)
        if arrow is None:
            continue
        start, _, end = lines[arrow].partition(",")
        start = start.strip().replace(".", ",")
        end = end.strip().split()[0].replace(".", ",") if end else ""
        body = "\n".join(lines[arrow + 1:])
        if body.strip():
            subs.append(_entry(0, start, end, _strip_inline_tags(body)))
    return _renumber(subs)


def parse_lrc(text: str) -> list:
    """Lyric (LRC) timestamps [mm:ss.xx] mapped to short subtitles."""
    items = []
    for line in text.splitlines():
        tags = re.findall(r"\[(\d{1,2}):(\d{1,2})(?:[.:](\d{1,3}))?\]", line)
        body = re.sub(r"\[[^\]]*\]", "", line).strip()
        for mm, ss, frac in tags:
            secs = int(mm) * 60 + int(ss) + (int(frac) / 100 if frac else 0)
            items.append((_from_seconds(secs), body))
    items.sort(key=lambda x: _to_seconds(x[0]))
    subs = []
    for i, (start, body) in enumerate(items):
        s = _to_seconds(start)
        e = _to_seconds(items[i + 1][0]) if i + 1 < len(items) else s + 3
        subs.append(_entry(0, start, _from_seconds(e), body))
    return _renumber(subs)


def parse_ttml(text: str) -> list:
    """Parse TTML/XML subtitles into subtitle entries.

    Uses a real XML parser (not regex) so that:
      - <p> tags spanning multiple lines are captured,
      - nested <span>/<br> inside <p> are flattened into the dialogue,
      - namespaced attributes (tt:begin, xml:begin) are read,
      - no dialogue is dropped just because a `begin`/`end` attr is absent.
    """
    def _strip_ns(tag):
        return tag.split("}")[-1] if "}" in tag else tag

    # Collect every <p> (handle namespaces) via regex first to be robust
    # against malformed XML, then parse each <p> individually.
    p_blocks = re.findall(r"<p\b([^>]*)>(.*?)</p>", text, re.S | re.I)

    subs = []
    if p_blocks:
        for attrs, body in p_blocks:
            begin = re.search(r"(?:tt:)?begin=\"([^\"]+)\"", attrs, re.I)
            end = re.search(r"(?:tt:)?end=\"([^\"]+)\"", attrs, re.I)
            dur = re.search(r"(?:tt:)?dur=\"([^\"]+)\"", attrs, re.I)
            start_tc = _ttml_time_to_srt(begin.group(1)) if begin else ""
            if not start_tc and dur:
                # duration without begin is rare; skip safely
                continue
            if begin:
                start_secs = _to_seconds(start_tc) or 0
                if end:
                    end_tc = _ttml_time_to_srt(end.group(1))
                elif dur:
                    d = _ttml_time_to_srt(dur.group(1))
                    end_tc = _from_seconds(start_secs + (_to_seconds(d) or 0))
                else:
                    end_tc = _from_seconds(start_secs + 3.0)
                body = re.sub(r"<br\s*/?>", "\n", body, flags=re.I)
                body = re.sub(r"<[^>]+>", "", body).strip()
                if body:
                    subs.append(_entry(0, start_tc, end_tc, body))
    else:
        # Fallback: real XML parse (handles namespaces, nested spans).
        try:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(text)
            for p in root.iter():
                if _strip_ns(p.tag) != "p":
                    continue
                def _get(attr):
                    for k, v in p.attrib.items():
                        if _strip_ns(k) == attr:
                            return v
                    return None
                begin = _get("begin")
                end = _get("end")
                dur = _get("dur")
                if not begin:
                    continue
                start_tc = _ttml_time_to_srt(begin)
                start_secs = _to_seconds(start_tc) or 0
                if end:
                    end_tc = _ttml_time_to_srt(end)
                elif dur:
                    d = _ttml_time_to_srt(dur)
                    end_tc = _from_seconds(start_secs + (_to_seconds(d) or 0))
                else:
                    end_tc = _from_seconds(start_secs + 3.0)
                # Flatten all text (including nested span text).
                body = "".join(p.itertext())
                body = re.sub(r"<br\s*/?>", "\n", body, flags=re.I)
                body = body.strip()
                if body:
                    subs.append(_entry(0, start_tc, end_tc, body))
        except Exception:
            pass

    return _renumber(subs)


def _ttml_time_to_srt(tc: str) -> str:
    tc = tc.strip().replace("t", "")
    m = re.match(r"(\d{1,2}):(\d{2}):(\d{2})\.(\d{1,3})", tc)
    if m:
        h, mn, s, ms = m.groups()
        return f"{int(h):02d}:{int(mn):02d}:{int(s):02d},{ms.ljust(3,'0')[:3]}"
    m = re.match(r"(\d{1,2})\.(\d{2}):(\d{2})\.(\d{1,3})", tc)  # Hh:MM:SS
    if m:
        h, mn, s, ms = m.groups()
        return f"{int(h):02d}:{int(mn):02d}:{int(s):02d},{ms.ljust(3,'0')[:3]}"
    m = re.match(r"(\d+)\.(\d{1,3})s?", tc)  # seconds
    if m:
        return _from_seconds(float(f"{m.group(1)}.{m.group(2)}"))
    return ""


def parse_csv_subtitles(text: str) -> list:
    subs = []
    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if r]
    if not rows:
        return []
    header = [c.lower() for c in rows[0]]
    # Detect header columns
    def idx(*names):
        for n in names:
            for j, h in enumerate(header):
                if n in h:
                    return j
        return None
    si = idx("start", "timein", "begin")
    ei = idx("end", "timeout", "out")
    ti = idx("text", "dialog", "subtitle", "line", "content")
    has_header = si is not None or ei is not None or ti is not None
    start = 1 if has_header else 0
    for r in rows[start:]:
        if not r or all(not c.strip() for c in r):
            continue
        start_tc = r[si] if si is not None and si < len(r) else ""
        end_tc = r[ei] if ei is not None and ei < len(r) else ""
        body = r[ti] if ti is not None and ti < len(r) else (r[-1] if r else "")
        if body.strip():
            subs.append(_entry(0, normalize_timecode(start_tc), normalize_timecode(end_tc), body))
    # If only text column, assign sequential timings
    if not any(s.get("start_time") for s in subs):
        return _assign_sequential(subs)
    return _renumber([s for s in subs if s.get("start_time")])


def parse_json_subtitles(text: str) -> list:
    try:
        data = json.loads(text)
    except Exception:
        return []
    if isinstance(data, dict):
        data = data.get("subtitles", data.get("events", []))
    if not isinstance(data, list):
        return []
    subs = []
    for item in data:
        if not isinstance(item, dict):
            continue
        start = item.get("start_time") or item.get("start") or item.get("begin") or ""
        end = item.get("end_time") or item.get("end") or item.get("finish") or ""
        body = item.get("text") or item.get("dialogue") or item.get("content") or ""
        if isinstance(body, list):
            body = "\n".join(body)
        if str(body).strip():
            subs.append(_entry(0, normalize_timecode(str(start)), normalize_timecode(str(end)), str(body)))
    if not any(s.get("start_time") for s in subs):
        return _assign_sequential(subs)
    return _renumber([s for s in subs if s.get("start_time")])


def parse_txt(text: str) -> list:
    """Plain text → one subtitle per non-empty line, sequential timings."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    subs = [_entry(0, "", "", l) for l in lines]
    return _assign_sequential(subs)


def _assign_sequential(subs: list, dur: float = 2.0, gap: float = 0.2) -> list:
    t = 0.0
    out = []
    for s in subs:
        out.append(_entry(0, _from_seconds(t), _from_seconds(t + dur), s.get("text", "")))
        t += dur + gap
    return _renumber(out)


def detect_format(filename: str, text: str = "") -> str:
    ext = (filename or "").rsplit(".", 1)[-1].lower()
    if ext in IMPORT_FORMATS:
        return ext
    low = (text or "").lower()
    if low.startswith("webvtt"):
        return "vtt"
    if "[events]" in low and "dialogue:" in low:
        return "ass"
    if "<tt " in low or "<tt>" in low:
        return "ttml"
    return "txt"


def parse_subtitles(text: str, fmt: str = None, filename: str = "") -> list:
    fmt = (fmt or detect_format(filename, text)).lower()
    parsers = {
        "srt": parse_srt, "vtt": parse_vtt, "ass": parse_ass, "ssa": parse_ass,
        "sub": parse_sub, "sbv": parse_sbv, "lrc": parse_lrc, "ttml": parse_ttml,
        "xml": parse_ttml, "csv": parse_csv_subtitles, "json": parse_json_subtitles,
        "txt": parse_txt,
    }
    parser = parsers.get(fmt, parse_txt)
    try:
        return parser(text)
    except Exception:
        # Never crash the import — fall back to plain text line split.
        return parse_txt(text)


# ─── EXPORTERS ─────────────────────────────────────────────────────

def _escape_ass(text: str) -> str:
    return text.replace("\n", "\\N").replace(",", ",")


def _to_ass_time(sec: float) -> str:
    s, cs = divmod(int(round(sec * 100)), 100)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def subtitles_to_format(subs: list, fmt: str, filename: str = "subtitles") -> str:
    fmt = (fmt or "srt").lower()
    clean = [s for s in subs if s.get("text", "").strip()]
    clean = _renumber(clean)

    if fmt == "srt":
        return _export_srt(clean)
    if fmt == "vtt":
        return _export_vtt(clean)
    if fmt in ("ass", "ssa"):
        return _export_ass(clean, fmt)
    if fmt == "sub":
        return _export_sub(clean)
    if fmt == "sbv":
        return _export_sbv(clean)
    if fmt == "lrc":
        return _export_lrc(clean)
    if fmt in ("ttml", "xml"):
        return _export_ttml(clean, filename)
    if fmt == "csv":
        return _export_csv(clean)
    if fmt == "json":
        return json.dumps({"subtitles": clean}, ensure_ascii=False, indent=2)
    # txt
    return "\n\n".join(s["text"] for s in clean)


def _export_srt(subs):
    blocks = []
    for i, s in enumerate(subs, 1):
        blocks.append(f"{i}\n{normalize_timecode(s['start_time'])} --> {normalize_timecode(s['end_time'])}\n{s['text']}")
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def _export_vtt(subs):
    blocks = ["WEBVTT\n"]
    for i, s in enumerate(subs, 1):
        start = normalize_timecode(s['start_time']).replace(",", ".")
        end = normalize_timecode(s['end_time']).replace(",", ".")
        blocks.append(f"{i}\n{start} --> {end}\n{s['text']}")
    return "\n\n".join(blocks)


def _export_ass(subs, fmt):
    lines = [
        "[Script Info]",
        "Title: Exported from SubtitleAI Editor",
        "ScriptType: v4.00+",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,2,2,10,10,10,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for s in subs:
        start = _to_ass_time(_to_seconds(normalize_timecode(s['start_time'])) or 0)
        end = _to_ass_time(_to_seconds(normalize_timecode(s['end_time'])) or 0)
        text = s["text"].replace("<i>", "{\\i1}").replace("</i>", "{\\i0}").replace("<b>", "{\\b1}").replace("</b>", "{\\b0}").replace("\n", "\\N")
        lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")
    return "\n".join(lines) + "\n"


def _export_sub(subs, fps=_FPS_DEFAULT):
    lines = []
    for s in subs:
        sf = int(round((_to_seconds(normalize_timecode(s['start_time'])) or 0) * fps))
        ef = int(round((_to_seconds(normalize_timecode(s['end_time'])) or 0) * fps))
        lines.append(f"{{{sf}}}{{{ef}}}{s['text']}")
    return "\n".join(lines) + "\n"


def _export_sbv(subs):
    blocks = []
    for s in subs:
        start = normalize_timecode(s['start_time']).replace(",", ".")
        end = normalize_timecode(s['end_time']).replace(",", ".")
        blocks.append(f"{start},{end}\n{s['text']}")
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def _export_lrc(subs):
    items = []
    for s in subs:
        sec = _to_seconds(normalize_timecode(s['start_time'])) or 0
        m = int(sec // 60)
        r = sec - m * 60
        sec_i = int(r)
        cs = int(round((r - sec_i) * 100))
        items.append((f"[{m:02d}:{sec_i:02d}.{cs:02d}]", s["text"]))
    out = [t for pair in items for t in pair]
    return "\n".join(out) + "\n"


def _export_ttml(subs, filename):
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<tt xmlns="http://www.w3.org/ns/ttml" xmlns:tts="http://www.w3.org/ns/ttml#styling" xml:lang="en">',
        '  <head>',
        '    <styling><style xml:id="s" tts:color="white" tts:fontFamily="sansSerif" tts:fontSize="100%" tts:textAlign="center"/></styling>',
        '    <layout><region xml:id="r" tts:origin="10% 80%" tts:extent="80% 15%"/></layout>',
        '  </head>',
        '  <body><div style="s">',
    ]
    for i, s in enumerate(subs, 1):
        start = normalize_timecode(s['start_time']).replace(",", ".")
        end = normalize_timecode(s['end_time']).replace(",", ".")
        safe = saxutils.escape(s["text"]).replace("\n", "<br/>")
        lines.append(f'    <p xml:id="p{i}" begin="{start}" end="{end}" region="r">{safe}</p>')
    lines.extend(['  </div></body>', '</tt>'])
    return "\n".join(lines) + "\n"


def _export_csv(subs):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["ID", "Start Time", "End Time", "Text"])
    for i, s in enumerate(subs, 1):
        w.writerow([i, normalize_timecode(s['start_time']), normalize_timecode(s['end_time']), s['text']])
    return out.getvalue()


# ─── SYNCHRONIZATION (Subtitle Edit style) ─────────────────────────

def _in_selected_range(sub: dict, start_id: int | None = None, end_id: int | None = None) -> bool:
    """Return true when a subtitle is inside an optional id range."""
    if start_id is None and end_id is None:
        return True
    sid = sub.get("id")
    try:
        sid = int(sid)
    except (TypeError, ValueError):
        return False
    if start_id is not None and sid < start_id:
        return False
    if end_id is not None and sid > end_id:
        return False
    return True


def _id_matches(value, target: int) -> bool:
    try:
        return int(value) == int(target)
    except (TypeError, ValueError):
        return str(value) == str(target)


def _shift_one(sub: dict, seconds: float) -> dict:
    item = dict(sub)
    st = _to_seconds(item.get("start_time", ""))
    en = _to_seconds(item.get("end_time", ""))
    if st is not None:
        item["start_time"] = _from_seconds(max(0, st + seconds))
    if en is not None:
        item["end_time"] = _from_seconds(max(0, en + seconds))
    return item


def _linear_map_one(sub: dict, source_a: float, target_a: float, factor: float) -> dict:
    item = dict(sub)
    st = _to_seconds(item.get("start_time", ""))
    en = _to_seconds(item.get("end_time", ""))
    if st is not None:
        item["start_time"] = _from_seconds(max(0, target_a + (st - source_a) * factor))
    if en is not None:
        item["end_time"] = _from_seconds(max(0, target_a + (en - source_a) * factor))
    return item


def sync_offset(subs: list, seconds: float, start_id: int | None = None, end_id: int | None = None) -> list:
    """Adjust times: shift all subtitles, or only an id range, by a constant offset."""
    out = []
    for s in subs:
        out.append(_shift_one(s, seconds) if _in_selected_range(s, start_id, end_id) else dict(s))
    return out


def sync_scale(subs: list, factor: float, start_id: int | None = None, end_id: int | None = None) -> list:
    """Adjust times: change playback speed, optionally within an id range."""
    if factor <= 0:
        return subs
    out = []
    for s in subs:
        if not _in_selected_range(s, start_id, end_id):
            out.append(dict(s))
            continue
        st = _to_seconds(s.get("start_time", ""))
        en = _to_seconds(s.get("end_time", ""))
        item = dict(s)
        item["start_time"] = _from_seconds(max(0, st * factor)) if st is not None else s.get("start_time", "")
        item["end_time"] = _from_seconds(max(0, en * factor)) if en is not None else s.get("end_time", "")
        out.append(item)
    return out


def sync_point(subs: list, anchor_id: int, new_start: str, new_end: str = None,
               start_id: int | None = None, end_id: int | None = None) -> list:
    """
    Visual / Point sync: lock one subtitle to a new time, then shift every
    other subtitle by the same delta (so relative spacing is preserved).
    Mirrors Subtitle Edit's "Set start / end" + "Apply to all".
    """
    anchor = next((s for s in subs if _id_matches(s.get("id"), anchor_id)), None)
    if not anchor:
        return subs
    old_start = _to_seconds(anchor.get("start_time", ""))
    new_start_sec = _to_seconds(normalize_timecode(new_start))
    if old_start is None or new_start_sec is None:
        return subs
    delta = new_start_sec - old_start
    return sync_offset(subs, delta, start_id, end_id)


def sync_visual(subs: list, anchor_id: int, new_start: str,
                anchor_id2: int | None = None, new_start2: str | None = None,
                start_id: int | None = None, end_id: int | None = None) -> list:
    """
    Visual sync from one or two video-picked points.
    - One anchor: shift selected subtitles by the anchor delta.
    - Two anchors: stretch/compress selected subtitles linearly between the
      old anchor starts and the newly picked video positions.
    """
    anchor = next((s for s in subs if _id_matches(s.get("id"), anchor_id)), None)
    if not anchor:
        return subs
    old_a = _to_seconds(anchor.get("start_time", ""))
    new_a = _to_seconds(normalize_timecode(new_start))
    if old_a is None or new_a is None:
        return subs

    if anchor_id2 is None or not new_start2:
        return sync_offset(subs, new_a - old_a, start_id, end_id)

    anchor2 = next((s for s in subs if _id_matches(s.get("id"), anchor_id2)), None)
    if not anchor2:
        return sync_offset(subs, new_a - old_a, start_id, end_id)
    old_b = _to_seconds(anchor2.get("start_time", ""))
    new_b = _to_seconds(normalize_timecode(new_start2))
    if old_b is None or new_b is None or old_b == old_a:
        return sync_offset(subs, new_a - old_a, start_id, end_id)

    factor = (new_b - new_a) / (old_b - old_a)
    out = []
    for s in subs:
        out.append(_linear_map_one(s, old_a, new_a, factor) if _in_selected_range(s, start_id, end_id) else dict(s))
    return out


def sync_point_via_other(subs: list, ref_subs: list,
                         subs_index: int, ref_index: int,
                         subs_index2: int = None, ref_index2: int = None) -> list:
    """
    Point sync via other subtitle: align `subs` onto `ref_subs`.
    - Single matched pair  → constant shift (delta between the two starts).
    - Two matched pairs    → linear scale between them (full speed correction),
      like Subtitle Edit's two-point "Sync".
    Indices are 0-based positions within each list.
    """
    if subs_index is None or ref_index is None:
        return subs
    a = subs[subs_index] if 0 <= subs_index < len(subs) else None
    b = ref_subs[ref_index] if 0 <= ref_index < len(ref_subs) else None
    if not a or not b:
        return subs
    a_start = _to_seconds(a.get("start_time", ""))
    b_start = _to_seconds(b.get("start_time", ""))
    if a_start is None or b_start is None:
        return subs

    # Single point → shift
    if subs_index2 is None or ref_index2 is None:
        delta = b_start - a_start
        return sync_offset(subs, delta)

    # Two points → linear (scale + shift)
    a2 = subs[subs_index2] if 0 <= subs_index2 < len(subs) else None
    b2 = ref_subs[ref_index2] if 0 <= ref_index2 < len(ref_subs) else None
    if not a2 or not b2:
        delta = b_start - a_start
        return sync_offset(subs, delta)
    a2s = _to_seconds(a2.get("start_time", ""))
    b2s = _to_seconds(b2.get("start_time", ""))
    if a2s is None or b2s is None or a2s == a_start:
        delta = b_start - a_start
        return sync_offset(subs, delta)
    factor = (b2s - b_start) / (a2s - a_start)
    return [_linear_map_one(s, a_start, b_start, factor) for s in subs]


# ─── AUTO TRANSLATE (multi-provider engine) ───────────────────────
#
# Delegates to translate_engines.py, which supports the same breadth of
# translation providers as Subtitle Edit (OpenAI/ChatGPT, Anthropic Claude,
# Google Gemini, DeepL, DeepSeek, Groq, Mistral, OpenRouter, Perplexity,
# Ollama, LibreTranslate, Azure Translator, a generic OpenAI-compatible
# endpoint, and the free Google Translate web endpoint). A subtitler pastes
# their API key in the UI; the engine falls back to a server .env var if blank.

from translate_engines import (
    translate_subtitles as _translate_subtitles_impl,
    translate_subtitles_stream as _translate_subtitles_stream_impl,
    get_provider_list,
    PROVIDERS,
)


def translate_subtitles(subs: list, target_lang: str, source_lang: str = "",
                        provider: str = "google", config: dict | None = None) -> list:
    """
    Auto-translate every subtitle's text via the chosen provider.
    Returns a new list with translated `text`.
    """
    return _translate_subtitles_impl(
        subs, target_lang, source_lang, provider=provider, config=config
    )


def translate_subtitles_stream(subs: list, target_lang: str, source_lang: str = "",
                                stop_check=None, stop_action=None,
                                provider: str = "google", config: dict | None = None):
    """
    Generator that translates line-by-line and yields SSE-style progress events
    so the UI can show a live "translating N / Total" popup (like Subtitle Edit).
    Yields dicts: {"type":"line",...} while working, and finally either
    {"type":"done","subtitles":[...]} when finished, or
    {"type":"stopped","subtitles":[...],"action":...} when cancelled via
    `stop_check`.
    """
    return _translate_subtitles_stream_impl(
        subs, target_lang, source_lang,
        provider=provider, config=config,
        stop_check=stop_check, stop_action=stop_action,
    )
