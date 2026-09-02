"""Small, deterministic piecewise reference-to-client timeline transform."""

from bisect import bisect_right


def build_piecewise_mapping(anchors: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Validate and sort (reference_seconds, client_seconds) anchors."""
    clean = sorted((float(a), float(b)) for a, b in anchors)
    if len(clean) < 2:
        raise ValueError("At least two timeline anchors are required")
    if any(b <= a for (a, _), (b, _) in zip(clean, clean[1:])):
        raise ValueError("Reference anchors must increase")
    if any(b <= a for (_, a), (_, b) in zip(clean, clean[1:])):
        raise ValueError("Client anchors must increase")
    return clean


def transform_time(seconds: float, anchors: list[tuple[float, float]]) -> float:
    """Map a reference timestamp using linear interpolation/extrapolation."""
    points = build_piecewise_mapping(anchors)
    i = max(0, min(len(points) - 2, bisect_right([p[0] for p in points], seconds) - 1))
    r0, c0 = points[i]; r1, c1 = points[i + 1]
    return c0 + (seconds - r0) * (c1 - c0) / (r1 - r0)


def transform_subtitles(subtitles: list[dict], anchors: list[tuple[float, float]]) -> list[dict]:
    """Return copies with both cue boundaries mapped to client/GTS time."""
    result = []
    from timecoded_subtitles import _from_seconds, _to_seconds
    for sub in subtitles:
        item = dict(sub)
        start = _to_seconds(item.get("start_time", "")); end = _to_seconds(item.get("end_time", ""))
        if start is not None:
            item["start_time"] = _from_seconds(transform_time(start, anchors))
            item["start"] = item["start_time"]
        if end is not None:
            item["end_time"] = _from_seconds(transform_time(end, anchors))
            item["end"] = item["end_time"]
        item["timeline_alignment"] = "piecewise"
        result.append(item)
    return result


def classify_alignment(anchors, reference_duration=None, client_duration=None, tolerance=0.04):
    points = build_piecewise_mapping(anchors)
    slopes = [(b - a) / (d - c) for (c, a), (d, b) in zip(points, points[1:])]
    if all(abs(s - 1.0) <= tolerance for s in slopes):
        offset = points[0][1] - points[0][0]
        return "IDENTICAL" if abs(offset) <= tolerance else "GLOBAL_OFFSET"
    if len(slopes) == 1:
        return "FPS_TRANSFORM"
    return "PIECEWISE"


def align_subtitles_to_client(subtitles, anchors, reference_duration=None,
                              client_duration=None, client_fps=None, reference_fps=None):
    """Transform mapped reference cues and return a validated delivery report."""
    points = build_piecewise_mapping(anchors)
    kind = classify_alignment(points, reference_duration, client_duration)
    transformed = transform_subtitles(subtitles, points)
    warnings = []
    unresolved = 0
    mapped = 0
    previous_end = None
    for item in transformed:
        start = _seconds(item.get("start_time")); end = _seconds(item.get("end_time"))
        if start is None or end is None:
            unresolved += 1
            continue
        mapped += 1
        if end <= start:
            warnings.append(f"Subtitle {item.get('id', '?')} has non-positive duration")
        if previous_end is not None and start < previous_end - 0.001:
            warnings.append(f"Subtitle {item.get('id', '?')} overlaps the preceding cue")
        previous_end = end
        if client_duration is not None and (start < -0.001 or end > float(client_duration) + 0.001):
            warnings.append(f"Subtitle {item.get('id', '?')} exceeds client duration")
    if client_fps and reference_fps and abs(float(client_fps) - float(reference_fps)) > 0.001:
        warnings.append("FPS metadata differs; timestamps remain absolute seconds and are not frame-rounded here")
    confidence = sum(float(s.get("confidence", s.get("align_score", 0)) or 0) for s in transformed) / max(1, mapped)
    report = {"alignment_type": kind, "reference_duration": reference_duration,
              "client_duration": client_duration, "client_fps": client_fps,
              "reference_fps": reference_fps, "detected_anchors": points,
              "timeline_segments": len(points) - 1, "auto_mapped": mapped,
              "unresolved": unresolved, "confidence": round(confidence, 4),
              "warnings": warnings}
    return transformed, report


def _seconds(value):
    from timecoded_subtitles import _to_seconds
    return _to_seconds(value or "")
