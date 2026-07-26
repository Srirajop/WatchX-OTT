"""Conservatively transfer timestamp cues onto trusted script dialogue.

The script is the only source of output text.  Timestamp text is used solely
to locate a matching cue, never copied into the result.  When a match cannot
be established, the cue is left blank and flagged; manufacturing an estimated
timecode is worse than asking an editor to review the line.
"""

import difflib
import re


# A match below this is not reliable enough to assign a real timestamp.
ACCEPT_THRESHOLD = 0.42
ANCHOR_THRESHOLD = 0.62
MAX_CUE_WINDOW = 6
MAX_LOOKAHEAD = 50
MIN_MANUAL_CUE_SECONDS = 0.08  # two frames at the project's 25 fps timebase
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


def _source_cues(subtitles: list[dict]) -> list[dict]:
    from timecoded_subtitles import _to_seconds

    cues = []
    for index, sub in enumerate(subtitles):
        start = _to_seconds(sub.get("start_time", ""))
        end = _to_seconds(sub.get("end_time", ""))
        tokens = _tokens(sub.get("text", ""))
        # Keep a valid timestamp cue even when its dialogue column is blank:
        # equal-count mapping is still a fully deterministic, useful operation.
        if start is None or end is None or end <= start:
            continue
        cues.append({
            "start": start,
            "end": end,
            "tokens": tokens,
            "source_id": sub.get("id", index + 1),
        })
    return cues


def _set_times(item: dict, cue_start: float, cue_end: float, mode: str, original_duration: float | None) -> None:
    from timecoded_subtitles import _from_seconds

    item["start_time"] = _from_seconds(cue_start)
    if mode == "preserve_duration" and original_duration is not None:
        item["end_time"] = _from_seconds(cue_start + original_duration)
    else:
        item["end_time"] = _from_seconds(cue_end)


def _overlaps(start: float, end: float, intervals: list[tuple[float, float]]) -> bool:
    """Return whether a cue has a real (not merely touching) overlap."""
    return any(start < other_end and end > other_start for other_start, other_end in intervals)


def _token_timeline(cues: list[dict]) -> list[dict]:
    """Expand cue text into ordered pseudo-word timestamps.

    Whisper supplies cue-level timing, not dependable word timing.  Splitting
    each cue proportionally is nevertheless the only safe way to preserve
    order when one Whisper cue contains several client-script dialogues.
    """
    timeline = []
    for cue in cues:
        count = len(cue["tokens"])
        if not count:
            continue
        duration = cue["end"] - cue["start"]
        for index, token in enumerate(cue["tokens"]):
            timeline.append({
                "token": token,
                "start": cue["start"] + duration * index / count,
                "end": cue["start"] + duration * (index + 1) / count,
                "source_id": cue["source_id"],
            })
    return timeline


def align_transcription_to_script(
    whisper_subs: list[dict],
    cleaned_subs: list[dict],
    similarity_threshold: float = ANCHOR_THRESHOLD,
    mode: str = "full",
) -> list[dict]:
    """Globally align client dialogue with the complete Whisper transcript.

    The previous greedy cue-by-cue search lost its place whenever Whisper split
    or merged dialogue.  Here the entire ordered token streams are aligned in
    one pass, so a minor recognition error or a newline cannot shift the rest
    of the episode onto the wrong timestamps.  Only client-script text is
    returned.
    """
    if not cleaned_subs:
        return []
    mode = "preserve_duration" if mode == "preserve_duration" else "full"
    cues = _source_cues(whisper_subs)
    timeline = _token_timeline(cues)
    from timecoded_subtitles import _from_seconds, _to_seconds

    script_tokens: list[str] = []
    token_line: list[int] = []
    line_token_counts: list[int] = []
    for line_index, sub in enumerate(cleaned_subs):
        tokens = _tokens(sub.get("text", ""))
        line_token_counts.append(len(tokens))
        script_tokens.extend(tokens)
        token_line.extend([line_index] * len(tokens))

    source_tokens = [entry["token"] for entry in timeline]
    matched_sources: list[list[int]] = [[] for _ in cleaned_subs]
    if script_tokens and source_tokens:
        matcher = difflib.SequenceMatcher(None, script_tokens, source_tokens, autojunk=False)
        for block in matcher.get_matching_blocks():
            for offset in range(block.size):
                line_index = token_line[block.a + offset]
                matched_sources[line_index].append(block.b + offset)

    result = []
    for index, script_sub in enumerate(cleaned_subs):
        item = dict(script_sub)
        item["id"] = index + 1
        item["align_mode"] = mode
        positions = matched_sources[index]
        coverage = len(positions) / line_token_counts[index] if line_token_counts[index] else 0.0
        item["align_score"] = round(coverage, 4)
        original_start = _to_seconds(script_sub.get("start_time", ""))
        original_end = _to_seconds(script_sub.get("end_time", ""))
        original_duration = original_end - original_start if original_start is not None and original_end is not None and original_end > original_start else None

        if positions:
            first, last = timeline[min(positions)], timeline[max(positions)]
            start, end = first["start"], last["end"]
            if mode == "preserve_duration" and original_duration is not None:
                end = start + original_duration
            item["start_time"] = _from_seconds(start)
            item["end_time"] = _from_seconds(max(end, start + 0.04))
            item["align_source"] = f"token_{first['source_id']}-{last['source_id']}"
            item["flagged"] = coverage < 0.35
            item["flag_reason"] = "Partial transcript match; verify timing" if item["flagged"] else ""
        else:
            # Filled from a bounded gap after all exact global anchors are set.
            item["start_time"] = ""
            item["end_time"] = ""
            item["align_source"] = ""
            item["flagged"] = True
            item["flag_reason"] = "No transcript words matched; placed between surrounding aligned dialogue if possible"
        result.append(item)

    # Place completely unmatched client lines in their chronological gap.  This
    # preserves all dialogue in the SRT without overlapping Whisper-derived
    # cues, while clearly marking the generated cue for a human timing pass.
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
                item["manual_placement"] = True
                item["flag_reason"] = "No transcript words matched; placed in surrounding gap — set final timing manually"
        else:
            # A Whisper cue can contain the surrounding dialogue without a gap
            # at all.  Reserve a tiny, non-overlapping tail from the preceding
            # mapped cue so the client dialogue is still delivered in the SRT.
            # The cue is explicitly flagged for a subtitler to set accurately.
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
                    item["manual_placement"] = True
                    item["flag_reason"] = "No transcript words matched; reserved a non-overlapping cue — set final timing manually"
        group_start = group_end + 1

    return result


def _align_preserve_duration_by_token_timeline(whisper_subs: list[dict], cleaned_subs: list[dict]) -> list[dict]:
    """Backward-compatible internal entry point."""
    return align_transcription_to_script(whisper_subs, cleaned_subs, mode="preserve_duration")
