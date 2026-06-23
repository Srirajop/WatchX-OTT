# timecode_adjuster.py — Shift subtitle timecodes forward/backward or set new start
# Case 3: When timecodes from the script are slightly off from the actual video

import re


_FPS = 25

# Minimum gap between subtitles (SDI House Protocol: 2 frames at 25fps)
_MIN_GAP_SECONDS = 2 / 25  # 0.08s


def _tc_to_seconds(tc: str) -> float | None:
    """Convert SRT timecode (HH:MM:SS,mmm) or frame TC to seconds."""
    if not tc:
        return None
    tc = tc.strip().replace(';', ':')
    # SRT format: HH:MM:SS,mmm
    m = re.match(r'^(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})$', tc)
    if m:
        h, mn, s, ms = m.groups()
        ms_str = ms.ljust(3, '0')
        return int(h) * 3600 + int(mn) * 60 + int(s) + int(ms_str) / 1000
    # Frame TC: HH:MM:SS:FF
    m = re.match(r'^(\d{1,2}):(\d{2}):(\d{2}):(\d{1,2})$', tc)
    if m:
        h, mn, s, f = m.groups()
        return int(h) * 3600 + int(mn) * 60 + int(s) + int(f) / _FPS
    # HH:MM:SS only
    m = re.match(r'^(\d{1,2}):(\d{2}):(\d{2})$', tc)
    if m:
        h, mn, s = m.groups()
        return int(h) * 3600 + int(mn) * 60 + int(s)
    return None


def _seconds_to_srt(seconds: float) -> str:
    """Convert seconds to SRT format HH:MM:SS,mmm snapped to 25 FPS grid."""
    if seconds < 0:
        seconds = 0.0
    frames_total = round(seconds * _FPS)
    s_total, f = divmod(frames_total, _FPS)
    m_total, s = divmod(s_total, 60)
    h, mn = divmod(m_total, 60)
    ms = round((f / _FPS) * 1000)
    return f"{int(h):02d}:{int(mn):02d}:{int(s):02d},{int(ms):03d}"


def shift_timecodes(subtitles: list[dict], offset_seconds: float) -> list[dict]:
    """
    Shift ALL subtitle timecodes by offset_seconds.
    Positive = push forward (later), negative = pull back (earlier).
    Timecodes that would go below 0 are clamped to 0.
    """
    result = []
    for sub in subtitles:
        item = dict(sub)
        start = _tc_to_seconds(sub.get("start_time", ""))
        end = _tc_to_seconds(sub.get("end_time", ""))
        if start is not None:
            item["start_time"] = _seconds_to_srt(max(0.0, start + offset_seconds))
        if end is not None:
            item["end_time"] = _seconds_to_srt(max(0.0, end + offset_seconds))
        result.append(item)
    return result


def set_start_timecode(subtitles: list[dict], new_start_tc: str) -> list[dict]:
    """
    Shift all timecodes so the FIRST subtitle starts at new_start_tc.
    Every other subtitle is shifted by the same delta to preserve relative timing.
    """
    if not subtitles:
        return subtitles

    # Find the first subtitle that has a timecode
    first_start = None
    for sub in subtitles:
        s = _tc_to_seconds(sub.get("start_time", ""))
        if s is not None:
            first_start = s
            break

    new_start = _tc_to_seconds(new_start_tc)
    if first_start is None or new_start is None:
        return subtitles

    offset = new_start - first_start
    return shift_timecodes(subtitles, offset)


def fix_from_index(subtitles: list[dict], target_id: int, new_tc: str) -> list[dict]:
    """
    Change the timecode of subtitle with id=target_id to new_tc,
    then shift ALL subsequent subtitles by the same delta to preserve
    relative spacing. Subtitles BEFORE target_id are untouched.

    target_id: the subtitle's 'id' field (1-indexed)
    new_tc: the new start timecode for that subtitle (SRT or frame TC)
    """
    if not subtitles:
        return subtitles

    new_start = _tc_to_seconds(new_tc)
    if new_start is None:
        return subtitles

    result = []
    delta = None

    for sub in subtitles:
        item = dict(sub)
        sub_id = sub.get("id", 0)

        if sub_id == target_id:
            # Compute delta from original start to new start
            old_start = _tc_to_seconds(sub.get("start_time", ""))
            if old_start is not None:
                delta = new_start - old_start
            # Apply new start; adjust end by same delta
            item["start_time"] = _seconds_to_srt(max(0.0, new_start))
            if delta is not None:
                old_end = _tc_to_seconds(sub.get("end_time", ""))
                if old_end is not None:
                    item["end_time"] = _seconds_to_srt(max(0.0, old_end + delta))

        elif sub_id is not None and isinstance(sub_id, int) and sub_id > target_id and delta is not None:
            # Shift all subsequent subtitles by the same delta
            start = _tc_to_seconds(sub.get("start_time", ""))
            end = _tc_to_seconds(sub.get("end_time", ""))
            if start is not None:
                item["start_time"] = _seconds_to_srt(max(0.0, start + delta))
            if end is not None:
                item["end_time"] = _seconds_to_srt(max(0.0, end + delta))

        result.append(item)

    return result


def shift_only_this(
    subtitles: list[dict],
    target_id: int,
    new_start_tc: str,
    new_end_tc: str,
) -> dict:
    """
    Change ONLY the start and end timecode of subtitle with id=target_id.
    All other subtitles are completely untouched.

    Returns a dict:
      {
        "subtitles": [...],           # updated list
        "collision": True/False,      # whether new TCs overlap a neighbor
        "collision_detail": "...",    # human-readable description if collision
      }
    """
    new_start = _tc_to_seconds(new_start_tc)
    new_end   = _tc_to_seconds(new_end_tc)
    if new_start is None or new_end is None:
        return {"subtitles": subtitles, "collision": False, "collision_detail": ""}

    if new_end <= new_start:
        return {
            "subtitles": subtitles,
            "collision": True,
            "collision_detail": f"End timecode ({new_end_tc}) must be after start timecode ({new_start_tc}).",
        }

    # Find target, previous, and next subtitle with timecodes
    target_idx = None
    prev_sub   = None
    next_sub   = None

    for i, sub in enumerate(subtitles):
        if sub.get("id") == target_id:
            target_idx = i
            for j in range(i - 1, -1, -1):
                if subtitles[j].get("end_time"):
                    prev_sub = subtitles[j]
                    break
            for j in range(i + 1, len(subtitles)):
                if subtitles[j].get("start_time"):
                    next_sub = subtitles[j]
                    break
            break

    if target_idx is None:
        return {"subtitles": subtitles, "collision": False, "collision_detail": ""}

    # Collision checks
    collision = False
    collision_parts = []

    if prev_sub:
        prev_end = _tc_to_seconds(prev_sub.get("end_time", ""))
        if prev_end is not None and new_start < prev_end + _MIN_GAP_SECONDS:
            gap = new_start - prev_end
            collision = True
            collision_parts.append(
                f"Overlaps subtitle #{prev_sub.get('id')} — gap would be {gap*1000:.0f}ms "
                f"(min {_MIN_GAP_SECONDS*1000:.0f}ms). "
                f"Prev ends at {prev_sub.get('end_time')}."
            )

    if next_sub:
        next_start = _tc_to_seconds(next_sub.get("start_time", ""))
        if next_start is not None and new_end > next_start - _MIN_GAP_SECONDS:
            gap = next_start - new_end
            collision = True
            collision_parts.append(
                f"Overlaps subtitle #{next_sub.get('id')} — gap would be {gap*1000:.0f}ms "
                f"(min {_MIN_GAP_SECONDS*1000:.0f}ms). "
                f"Next starts at {next_sub.get('start_time')}."
            )

    # Apply changes regardless (frontend can decide whether to block or warn)
    result = []
    for sub in subtitles:
        item = dict(sub)
        if sub.get("id") == target_id:
            item["start_time"] = _seconds_to_srt(max(0.0, new_start))
            item["end_time"]   = _seconds_to_srt(max(0.0, new_end))
        result.append(item)

    return {
        "subtitles": result,
        "collision": collision,
        "collision_detail": " | ".join(collision_parts) if collision_parts else "",
    }


def parse_offset_input(value: str) -> float | None:
    """
    Parse user-supplied offset string:
    - "+2.5" or "2.5" → +2.5 seconds
    - "-1.04" → -1.04 seconds
    - "+00:00:02:12" (HH:MM:SS:FF) → seconds from frame TC
    - "-00:00:01,500" (SRT) → negative seconds
    Returns None on failure.
    """
    value = value.strip()
    if not value:
        return None

    sign = 1.0
    raw = value
    if value.startswith('+'):
        sign = 1.0
        raw = value[1:]
    elif value.startswith('-'):
        sign = -1.0
        raw = value[1:]

    # Try plain float
    try:
        return sign * float(raw)
    except ValueError:
        pass

    # Try timecode string
    secs = _tc_to_seconds(raw)
    if secs is not None:
        return sign * secs

    return None
