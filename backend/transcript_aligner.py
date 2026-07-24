# transcript_aligner.py — Maps Whisper-transcribed timecodes to cleaned script text
# Case: OTT script has correct dialogues (may lack timestamps or timestamps are wrong).
#       Whisper transcript has accurate timestamps but mishears/hallucinates words.
# Goal: Keep OTT script text EXACTLY as-is; borrow timestamps from Whisper.
#
# Algorithm:
#   1. Normalize both sides to word-token lists.
#   2. Compute a similarity matrix: each (cleaned_line, whisper_window) pair gets a
#      score combining word-overlap, token ratio, and subsequence coverage.
#   3. Run a monotonic dynamic-programming alignment to find the globally best
#      assignment of cleaned lines → Whisper segments (respects temporal order).
#   4. High-confidence anchors (score ≥ ANCHOR_THRESHOLD) are fixed first.
#   5. Low-confidence gaps between anchors are filled by interpolating timecodes
#      from the surrounding anchors proportionally.

import re
import difflib
from typing import Optional


# ── Tuning constants ──────────────────────────────────────────────────────────
ANCHOR_THRESHOLD  = 0.28   # score ≥ this → use Whisper timecode directly
ACCEPT_THRESHOLD  = 0.18   # score ≥ this → accept but flag for review
MAX_WINDOW        = 6      # max consecutive Whisper segments to merge for one cleaned line
MAX_LOOKAHEAD     = 50     # how many Whisper segs ahead to search (per cleaned line)
# ─────────────────────────────────────────────────────────────────────────────


def _normalize(text: str) -> str:
    """Lowercase, strip HTML/punctuation, collapse whitespace."""
    text = text.lower()
    text = re.sub(r"<[^>]+>", "", text)       # strip italic/bold tags
    text = re.sub(r"[^\w\s]", " ", text)      # remove punctuation
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _tokens(text: str) -> list[str]:
    return _normalize(text).split()


def _similarity(a_tokens: list[str], b_tokens: list[str]) -> float:
    """
    Multi-signal similarity between two token lists — robust against Whisper
    mishearing individual words.

    Signals combined:
      1. SequenceMatcher ratio        — sensitive to word order
      2. Jaccard word overlap         — robust when order slightly differs
      3. Longest common subsequence   — handles inserted/deleted tokens
      4. Length-penalty               — discourages matching very short queries
                                        against very long Whisper windows
    """
    if not a_tokens or not b_tokens:
        return 0.0

    # 1. SequenceMatcher ratio (word-level)
    sm = difflib.SequenceMatcher(None, a_tokens, b_tokens, autojunk=False)
    ratio = sm.ratio()

    # 2. Jaccard word overlap (ignores order)
    a_set = set(a_tokens)
    b_set = set(b_tokens)
    # Remove stop words that add noise
    stops = {"the","a","an","and","or","but","in","on","at","to","of","is",
             "it","i","we","he","she","they","you","was","were","be","are","for"}
    a_content = a_set - stops
    b_content = b_set - stops
    if a_content or b_content:
        jaccard = len(a_content & b_content) / len(a_content | b_content) if (a_content | b_content) else 0.0
    else:
        jaccard = len(a_set & b_set) / len(a_set | b_set) if (a_set | b_set) else 0.0

    # 3. How many of the cleaned line's tokens appear (in order) in the window?
    #    This is the "coverage" signal — key for Whisper which often ADDS words
    #    but rarely REMOVES them entirely from the original script.
    matched_blocks = sum(size for _, _, size in sm.get_matching_blocks())
    coverage = matched_blocks / len(a_tokens) if a_tokens else 0.0

    # 4. Length penalty: if the window is 4x larger than the cleaned line, boost less
    len_ratio = len(a_tokens) / max(len(b_tokens), 1)
    len_penalty = min(1.0, len_ratio * 2.0)

    score = (ratio * 0.35 + jaccard * 0.30 + coverage * 0.25 + len_penalty * 0.10)
    return round(score, 4)


def _align_preserve_out_by_token_timeline(
    whisper_subs: list[dict],
    cleaned_subs: list[dict],
) -> list[dict]:
    return align_transcription_to_script(whisper_subs, cleaned_subs, mode="preserve_out")


def align_transcription_to_script(
    whisper_subs: list[dict],   # Whisper/timestamp output — has timecodes, text may be rough
    cleaned_subs: list[dict],   # OTT script — has correct text, timecodes may be unreliable or missing
    similarity_threshold: float = ANCHOR_THRESHOLD,
    mode: str = "full",          # "full" | "preserve_out"
) -> list[dict]:
    """
    Transfer Whisper / source timestamps onto OTT cleaned script lines.
    The cleaned text is NEVER modified — only start_time / end_time are assigned.
    """
    if not whisper_subs or not cleaned_subs:
        return cleaned_subs

    from timecoded_subtitles import _to_seconds, _from_seconds

    _preserve_out = mode == "preserve_out"

    # Build normalized source cue windows. The timestamp file is already synced
    # to video, so prefer whole cue boundaries over guessed per-token timings.
    # The previous implementation aligned against a free token timeline and used
    # the last token's estimated start as the out-cue; that made mapped cues end
    # too early and allowed drift after one weak match.
    source_segments: list[dict] = []
    for seg_idx, sub in enumerate(whisper_subs):
        tokens = _tokens(sub.get("text", ""))
        if not tokens:
            continue
        start = _to_seconds(sub.get("start_time", ""))
        end = _to_seconds(sub.get("end_time", ""))
        if start is None or end is None:
            continue
        if end <= start:
            end = start + max(0.2, len(tokens) * 0.18)
        source_segments.append({
            "tokens": tokens,
            "start": start,
            "end": end,
            "source_id": sub.get("id", seg_idx + 1),
        })

    if not source_segments:
        return cleaned_subs

    timeline: list[dict] = []
    for seg in source_segments:
        duration = seg["end"] - seg["start"]
        count = len(seg["tokens"])
        for tok_idx, token in enumerate(seg["tokens"]):
            token_start = seg["start"] + duration * (tok_idx / max(count, 1))
            token_end = seg["start"] + duration * ((tok_idx + 1) / max(count, 1))
            timeline.append({
                "token": token,
                "start": token_start,
                "end": max(token_end, token_start + 0.04),
                "source_id": seg["source_id"],
            })

    result: list[dict] = []
    cursor = 0
    total_tokens = len(timeline)

    for out_idx, cleaned_sub in enumerate(cleaned_subs, start=1):
        item = dict(cleaned_sub)
        ct = _tokens(cleaned_sub.get("text", ""))
        original_end = cleaned_sub.get("end_time", "")
        original_end_ok = _to_seconds(original_end) is not None if original_end else False

        if not ct:
            item.setdefault("start_time", "")
            item.setdefault("end_time", original_end if (_preserve_out and original_end_ok) else "")
            item["id"] = out_idx
            result.append(item)
            continue

        best_score = 0.0
        best_start = -1
        best_end = -1
        min_len = max(1, int(len(ct) * 0.45))
        max_len = min(100, max(len(ct) + 12, int(len(ct) * 2.8)))
        search_start = cursor
        search_end = min(total_tokens, cursor + max(300, len(ct) * 24))
        target_len = len(ct)

        for start_pos in range(search_start, search_end):
            max_window_end = min(total_tokens, start_pos + max_len)
            window_tokens: list[str] = []
            for end_pos in range(start_pos + 1, max_window_end + 1):
                window_tokens.append(timeline[end_pos - 1]["token"])
                if len(window_tokens) < min_len:
                    continue
                if len(window_tokens) > max(120, target_len * 4):
                    break
                score = _similarity(ct, window_tokens)
                distance_penalty = max(0, start_pos - cursor) * 0.0015
                window_penalty = 0.0
                if len(window_tokens) > target_len * 3 and target_len >= 3:
                    window_penalty += 0.025
                adjusted = score - distance_penalty - window_penalty
                if adjusted > best_score:
                    best_score = adjusted
                    best_start = start_pos
                    best_end = end_pos

        item["align_score"] = round(max(best_score, 0.0), 4)
        item["align_mode"] = mode

        # Accept alignment if score meets ACCEPT_THRESHOLD (0.18)
        if best_start >= 0 and best_score >= ACCEPT_THRESHOLD:
            source_start = timeline[best_start]["start"]
            source_end = timeline[best_end - 1]["end"]
            item["start_time"] = _from_seconds(source_start)

            original_end_sec = _to_seconds(original_end) if original_end_ok else None
            can_preserve_out = (
                _preserve_out
                and original_end_sec is not None
                and original_end_sec > source_start + 0.2
            )
            if can_preserve_out:
                item["end_time"] = original_end
            else:
                item["end_time"] = _from_seconds(max(source_end, source_start + 0.2))

            start_source_id = timeline[best_start]["source_id"]
            end_source_id = timeline[best_end - 1]["source_id"]
            item["align_source"] = f"cue_{start_source_id}-{end_source_id}"
            cursor = max(cursor + 1, best_end)

            if best_score >= ANCHOR_THRESHOLD:
                item.setdefault("flagged", False)
                item.setdefault("flag_reason", "")
            else:
                item["flagged"] = True
                item["flag_reason"] = f"Low-confidence alignment (score: {best_score:.2f}) — please verify"
        else:
            # Low score / uncertain match: mark for interpolation, do not advance cursor far
            item["start_time"] = ""
            if _preserve_out and original_end_ok:
                item["end_time"] = original_end
            else:
                item["end_time"] = ""
            item["align_source"] = ""
            item["flagged"] = True
            item["flag_reason"] = f"Uncertain alignment (score: {best_score:.2f}) — will be interpolated"

        item["id"] = out_idx
        result.append(item)

    # Interpolate timecodes for any unmatched lines between anchors
    result = _interpolate_missing_timecodes(result, preserve_out=_preserve_out)

    for idx, sub in enumerate(result, start=1):
        sub["id"] = idx

    return result


def _interpolate_missing_timecodes(subtitles: list[dict], preserve_out: bool = False) -> list[dict]:
    """
    Fill missing timecodes by interpolating from neighbouring known timecodes.
    Evenly distributes the gap between the previous and next known timecodes
    across all unmatched lines between them.
    """
    from timecoded_subtitles import _to_seconds, _from_seconds

    n = len(subtitles)

    # Collect the positions and times of all anchors
    anchors: list[tuple[int, float, float]] = []  # (index, start_sec, end_sec)
    for i, sub in enumerate(subtitles):
        if sub.get("start_time") and sub.get("end_time"):
            s = _to_seconds(sub["start_time"])
            e = _to_seconds(sub["end_time"])
            if s is not None and e is not None:
                anchors.append((i, s, e))

    if not anchors:
        # No anchors at all — generate 3s slots from t=0
        for i, sub in enumerate(subtitles):
            if not sub.get("start_time"):
                t = i * 3.0
                sub["start_time"] = _from_seconds(t)
                if not (preserve_out and sub.get("end_time")):
                    sub["end_time"] = _from_seconds(t + 2.0)
        return subtitles

    # Fill gaps between consecutive anchors
    # Prepend a virtual anchor at t=0 if first real anchor is not at index 0
    if anchors[0][0] > 0:
        anchors.insert(0, (-1, max(0.0, anchors[0][1] - 3.0 * anchors[0][0]), 0.0))

    # Append a virtual end anchor
    if anchors[-1][0] < n - 1:
        last_end = anchors[-1][2]
        remaining = n - 1 - anchors[-1][0]
        anchors.append((n, last_end + 3.0 * remaining, last_end + 3.0 * remaining + 2.0))

    for k in range(len(anchors) - 1):
        a_idx, a_start, a_end = anchors[k]
        b_idx, b_start, b_end = anchors[k + 1]

        # Find all unmatched subs between a_idx and b_idx (exclusive)
        gap_indices = [i for i in range(a_idx + 1, b_idx) if not subtitles[i].get("start_time")]
        if not gap_indices:
            continue

        # Distribute the time gap evenly
        total_gap = b_start - a_end
        slot = total_gap / (len(gap_indices) + 1)

        for rank, gi in enumerate(gap_indices, start=1):
            t_start = a_end + slot * rank
            t_end   = t_start + max(1.5, slot * 0.85)
            subtitles[gi]["start_time"] = _from_seconds(max(0.0, t_start))
            if not (preserve_out and subtitles[gi].get("end_time")):
                subtitles[gi]["end_time"] = _from_seconds(max(0.0, t_end))

    return subtitles
