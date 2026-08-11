"""Map a trusted client script onto a synced Whisper transcript.

The client script is the ONLY source of output dialogue text.  Whisper's
timecodes are the ONLY source of output timing — they are frame-accurate and
synced to the video, whereas the script's own timecodes are frequently missing
or drifted.  So every output line keeps the script's words but adopts the
Whisper time range that best covers those words.

Alignment is a *monotone, ordered, greedy* walk through both streams:
  - Whisper cues are exploded into ordered word tokens, each carrying its
    proportional time range (Whisper gives cue timing, not word timing, so we
    split a cue evenly across its words — the only safe way to preserve order
    when one Whisper cue contains several script lines).
  - Each script line claims the best contiguous run of Whisper tokens starting
    at (or just after) the current cursor, then the cursor advances past the
    claimed tokens.  This guarantees in-order, non-overlapping, video-synced
    timecodes and naturally handles "many cues -> one line" and
    "one cue -> many lines".

A line that cannot be confidently matched is left blank and gap-filled later
(marked for a human timing pass) rather than guessing a wrong timecode.
"""

import difflib
import re

from timecoded_subtitles import _to_seconds, _from_seconds


# A match below this is not reliable enough to assign a real timestamp.
ACCEPT_THRESHOLD = 0.42
ANCHOR_THRESHOLD = 0.62
# Smallest cue we will manufacture when gap-filling (two frames at 25 fps).
MIN_MANUAL_CUE_SECONDS = 0.08
# How many Whisper tokens we may skip forward when the script line's words are
# not at the exact cursor (e.g. Whisper inserted filler the script never had).
_MAX_SKIP_TOKENS = 12
# Upper bound on how far ahead we search for a line's Whisper run.
_MAX_LOOKAHEAD_TOKENS = 400
# Upper bound on a single line's Whisper run length (in tokens).
_MAX_RUN_TOKENS = 80

_STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "of",
    "is", "it", "i", "we", "he", "she", "they", "you", "was", "were",
    "be", "are", "for",
}


def _normalize(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    text = re.sub(r"[^\w\s]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def _tokens(text: str) -> list[str]:
    return _normalize(text).split()


def _similarity(a_tokens: list[str], b_tokens: list[str]) -> float:
    """Return a conservative word-level similarity score."""
    if not a_tokens or not b_tokens:
        return 0.0

    matcher = difflib.SequenceMatcher(None, a_tokens, b_tokens, autojunk=False)
    ratio = matcher.ratio()
    matched = sum(size for _, _, size in matcher.get_matching_blocks())
    coverage = matched / len(a_tokens)

    a_content = set(a_tokens) - _STOP_WORDS
    b_content = set(b_tokens) - _STOP_WORDS
    if a_content:
        # Do not allow common stop words to create a false match.
        content_overlap = len(a_content & b_content) / len(a_content)
    else:
        content_overlap = len(set(a_tokens) & set(b_tokens)) / len(set(a_tokens))

    # A very long collection of cues is not a useful match for one script line.
    length_ratio = min(len(a_tokens), len(b_tokens)) / max(len(a_tokens), len(b_tokens))
    return round(0.40 * coverage + 0.35 * content_overlap + 0.15 * ratio + 0.10 * length_ratio, 4)


def _build_timeline(whisper_subs: list[dict]) -> list[dict]:
    """Expand Whisper cues into ordered pseudo-word tokens with time ranges."""
    timeline = []
    for sub in whisper_subs:
        start = _to_seconds(sub.get("start_time", ""))
        end = _to_seconds(sub.get("end_time", ""))
        if start is None or end is None or end <= start:
            continue
        toks = _tokens(sub.get("text", ""))
        if not toks:
            continue
        duration = end - start
        for index, token in enumerate(toks):
            timeline.append({
                "token": token,
                "start": start + duration * index / len(toks),
                "end": start + duration * (index + 1) / len(toks),
                "source_id": sub.get("id", len(timeline) + 1),
            })
    return timeline


def _assign_ordered(timeline: list[dict], script_lines: list[list[str]]) -> list:
    """Greedy monotone alignment. Returns per-line (start, end, score) or None."""
    wt_len = len(timeline)
    wt_ptr = 0
    assignments: list = []

    for line_toks in script_lines:
        if not line_toks:
            assignments.append(None)
            continue

        lookahead = min(wt_len, wt_ptr + _MAX_LOOKAHEAD_TOKENS)
        best = None  # (score, j, k)
        # Try runs starting anywhere from the cursor up to a small skip window,
        # so Whisper filler that the script never contained can be bypassed.
        for j in range(wt_ptr, min(wt_ptr + _MAX_SKIP_TOKENS + 1, wt_len + 1)):
            max_k = min(lookahead, j + max(_MAX_RUN_TOKENS, len(line_toks) * 4))
            for k in range(j + 1, max_k + 1):
                window = [timeline[t]["token"] for t in range(j, k)]
                score = _similarity(window, line_toks)
                if best is None or score > best[0]:
                    best = (score, j, k)

        if best is None or best[0] < ACCEPT_THRESHOLD:
            assignments.append(None)
            # Make forward progress so a single unmatched line cannot stall the
            # rest of the episode onto wrong timecodes.
            wt_ptr = min(wt_ptr + 1, wt_len)
            continue

        score, j, k = best
        assignments.append((timeline[j]["start"], timeline[k - 1]["end"], score))
        wt_ptr = k

    return assignments


def _gap_fill(result: list[dict]) -> None:
    """Place unmatched lines in the surrounding gap between aligned cues."""
    pending = [i for i, item in enumerate(result) if not item.get("start_time") and item.get("text", "").strip()]
    group_start = 0
    while group_start < len(pending):
        group_end = group_start
        while group_end + 1 < len(pending) and pending[group_end + 1] == pending[group_end] + 1:
            group_end += 1
        indices = pending[group_start:group_end + 1]
        previous_end = _to_seconds(result[indices[0] - 1].get("end_time", "")) if indices[0] else 0.0
        next_start = _to_seconds(result[indices[-1] + 1].get("start_time", "")) if indices[-1] + 1 < len(result) else None
        if previous_end is not None and next_start is not None and next_start - previous_end >= len(indices) * MIN_MANUAL_CUE_SECONDS:
            slot = (next_start - previous_end) / len(indices)
            for position, item_index in enumerate(indices):
                item = result[item_index]
                item["start_time"] = _from_seconds(previous_end + position * slot)
                item["end_time"] = _from_seconds(previous_end + (position + 1) * slot)
                item["align_source"] = "manual_gap"
                item["align_method"] = "gap"
                item["manual_placement"] = True
                item["flag_reason"] = "No transcript words matched; placed in surrounding gap — set final timing manually"
        else:
            donor_index = indices[0] - 1
            donor_start = _to_seconds(result[donor_index].get("start_time", "")) if donor_index >= 0 else None
            donor_end = _to_seconds(result[donor_index].get("end_time", "")) if donor_index >= 0 else None
            reservation = len(indices) * MIN_MANUAL_CUE_SECONDS
            if donor_start is not None and donor_end is not None and donor_end - donor_start >= reservation + MIN_MANUAL_CUE_SECONDS:
                reserved_start = donor_end - reservation
                result[donor_index]["end_time"] = _from_seconds(reserved_start)
                for position, item_index in enumerate(indices):
                    item = result[item_index]
                    item["start_time"] = _from_seconds(reserved_start + position * MIN_MANUAL_CUE_SECONDS)
                    item["end_time"] = _from_seconds(reserved_start + (position + 1) * MIN_MANUAL_CUE_SECONDS)
                    item["align_source"] = "manual_split"
                    item["align_method"] = "gap"
                    item["manual_placement"] = True
                    item["flag_reason"] = "No transcript words matched; reserved a non-overlapping cue — set final timing manually"
        group_start = group_end + 1


def align_transcription_to_script(
    whisper_subs: list[dict],
    cleaned_subs: list[dict],
    similarity_threshold: float = ANCHOR_THRESHOLD,
    mode: str = "full",
) -> list[dict]:
    """Align client script dialogue to the synced Whisper transcript.

    Returns one subtitle per script line.  Every line keeps the script's words
    but is timed from the Whisper cue range that best covers those words, so the
    result is synced to the video.  Lines with no confident match are gap-filled
    and flagged for a human timing pass.

    ``mode``:
      "full"             — adopt both in & out cues from Whisper (synced).
      "preserve_duration"— keep Whisper's start but, when the script line
                           carries its own valid duration, preserve that
                           duration; otherwise fall back to the Whisper span.
      "ai"               — run the deterministic alignment, then refine weak
                           lines with the Llama 3.1 8B model (Groq).
    """
    if not cleaned_subs:
        return []

    preserve = (mode == "preserve_duration")
    # "ai" was the old third UI option; keep it working as Full Map.
    if mode == "ai":
        mode = "full"
    # Mapping must return promptly for manual review. AI is an explicit review
    # action after the result is shown, not a blocking part of mapping.
    use_ai = False

    timeline = _build_timeline(whisper_subs)
    script_lines = [_tokens(sub.get("text", "")) for sub in cleaned_subs]

    assignments = _assign_ordered(timeline, script_lines)

    result = []
    for index, script_sub in enumerate(cleaned_subs):
        item = dict(script_sub)
        item["id"] = index + 1
        item["align_mode"] = mode
        item["align_method"] = ""
        item.setdefault("align_source", "")
        item.setdefault("manual_placement", False)

        original_start = _to_seconds(script_sub.get("start_time", ""))
        original_end = _to_seconds(script_sub.get("end_time", ""))
        original_duration = (
            original_end - original_start
            if original_start is not None and original_end is not None and original_end > original_start
            else None
        )

        asg = assignments[index]
        if asg is None:
            item["start_time"] = ""
            item["end_time"] = ""
            item["align_score"] = 0.0
            item["flagged"] = True
            item["flag_reason"] = "No transcript words matched; placed between surrounding aligned dialogue if possible"
            result.append(item)
            continue

        start, end, score = asg
        if preserve and original_duration is not None:
            end = start + original_duration
        item["start_time"] = _from_seconds(start)
        item["end_time"] = _from_seconds(max(end, start + 0.04))
        item["align_score"] = round(score, 4)
        item["flagged"] = score < ANCHOR_THRESHOLD
        item["align_source"] = "whisper"
        item["align_method"] = "whisper"
        item["flag_reason"] = "Partial transcript match; verify timing" if item["flagged"] else ""
        result.append(item)

    _gap_fill(result)

    if use_ai:
        try:
            from llm_aligner import refine_alignment_with_llm
            result = refine_alignment_with_llm(whisper_subs, result, mode=mode)
        except Exception as exc:  # AI is a best-effort enhancement only.
            print(f"[align] AI refinement skipped: {exc}")

    return result


def _align_preserve_duration_by_token_timeline(whisper_subs: list[dict], cleaned_subs: list[dict]) -> list[dict]:
    """Backward-compatible internal entry point."""
    return align_transcription_to_script(whisper_subs, cleaned_subs, mode="preserve_duration")
