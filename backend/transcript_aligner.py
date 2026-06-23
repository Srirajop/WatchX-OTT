# transcript_aligner.py — Maps Whisper-transcribed timecodes to cleaned script text
# Case 2: Script has partial/no timecodes — Whisper has timecodes but may hallucinate
# We align the WHISPER transcription's timecodes to the CLEANED script's text.

import re
import difflib
from typing import Optional


def _normalize_for_match(text: str) -> str:
    """Strip punctuation and lowercase for fuzzy matching."""
    text = text.lower()
    text = re.sub(r"<[^>]+>", "", text)       # strip HTML/italic tags
    text = re.sub(r"[^\w\s]", " ", text)      # remove punctuation
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _tokenize(text: str) -> list[str]:
    return _normalize_for_match(text).split()


def align_transcription_to_script(
    whisper_subs: list[dict],   # Whisper output — has timecodes but may have wrong text
    cleaned_subs: list[dict],   # Cleaned script — has correct text, may lack timecodes
    similarity_threshold: float = 0.35
) -> list[dict]:
    """
    Transfer Whisper timecodes to the cleaned script lines.

    Strategy:
    1. Build a token sequence from Whisper segments.
    2. For each cleaned subtitle line, find the best-matching Whisper segment(s)
       using SequenceMatcher similarity on word tokens.
    3. Assign the timecodes from the best-matching Whisper segment to the cleaned line.
    4. Lines that cannot be matched get interpolated timecodes.

    Returns a new list of subtitles (cleaned text + Whisper-derived timecodes).
    """
    if not whisper_subs or not cleaned_subs:
        return cleaned_subs

    # Pre-normalize Whisper segments for matching
    whisper_tokens_list = [_tokenize(s.get("text", "")) for s in whisper_subs]

    # Build a big joined token string and positional index for fast search
    whisper_text_tokens: list[tuple[int, str]] = []
    for seg_idx, tokens in enumerate(whisper_tokens_list):
        for token in tokens:
            whisper_text_tokens.append((seg_idx, token))

    result = []
    used_whisper_end_index = 0  # pointer so we search forward, not from scratch each time

    for cleaned_sub in cleaned_subs:
        text = cleaned_sub.get("text", "")
        if not text.strip():
            result.append(dict(cleaned_sub))
            continue

        # Already has timecodes — keep them
        if cleaned_sub.get("start_time") and cleaned_sub.get("end_time"):
            result.append(dict(cleaned_sub))
            continue

        clean_tokens = _tokenize(text)
        if not clean_tokens:
            result.append(dict(cleaned_sub))
            continue

        best_score = 0.0
        best_start_seg = None
        best_end_seg = None

        # Search forward through Whisper segments (with a backward window of 3 for safety)
        search_start = max(0, used_whisper_end_index - 3)

        for seg_idx in range(search_start, len(whisper_subs)):
            # Try to match this cleaned line against a window of 1-4 Whisper segments
            for window in range(1, 5):
                end_idx = min(seg_idx + window, len(whisper_subs))
                window_tokens: list[str] = []
                for wi in range(seg_idx, end_idx):
                    window_tokens.extend(whisper_tokens_list[wi])

                if not window_tokens:
                    continue

                score = difflib.SequenceMatcher(
                    None, clean_tokens, window_tokens
                ).ratio()

                if score > best_score:
                    best_score = score
                    best_start_seg = seg_idx
                    best_end_seg = end_idx - 1

            # Don't search too far ahead — the script and whisper are roughly aligned
            if seg_idx > used_whisper_end_index + 30:
                break

        item = dict(cleaned_sub)

        if best_score >= similarity_threshold and best_start_seg is not None:
            start_sub = whisper_subs[best_start_seg]
            end_sub = whisper_subs[best_end_seg]
            item["start_time"] = start_sub.get("start_time", "")
            item["end_time"] = end_sub.get("end_time", "")
            item["align_score"] = round(best_score, 3)
            item["align_source"] = f"whisper_seg_{best_start_seg+1}-{best_end_seg+1}"
            
            # Transfer low confidence flags from Whisper if any
            is_flagged = False
            reasons = []
            for seg in whisper_subs[best_start_seg:best_end_seg+1]:
                if seg.get("flagged"):
                    is_flagged = True
                    if seg.get("flag_reason"):
                        reasons.append(seg.get("flag_reason"))
            if is_flagged:
                item["flagged"] = True
                # De-duplicate reasons
                item["flag_reason"] = " | ".join(dict.fromkeys(reasons)) if reasons else "Low confidence transcription"

            used_whisper_end_index = best_end_seg + 1
        else:
            # Could not match — flag for review
            item["start_time"] = ""
            item["end_time"] = ""
            item["flagged"] = True
            item["flag_reason"] = f"Could not match to Whisper transcript (best score: {best_score:.2f})"
            item["align_score"] = round(best_score, 3)

        result.append(item)

    # Interpolate timecodes for unmatched lines
    result = _interpolate_missing_timecodes(result)

    return result


def _interpolate_missing_timecodes(subtitles: list[dict]) -> list[dict]:
    """
    Fill in missing timecodes by interpolating from neighbouring known timecodes.
    """
    from timecoded_subtitles import _to_seconds, _from_seconds

    n = len(subtitles)
    for i, sub in enumerate(subtitles):
        if sub.get("start_time") and sub.get("end_time"):
            continue

        # Find the nearest known timecodes before and after
        prev_end = None
        for j in range(i - 1, -1, -1):
            if subtitles[j].get("end_time"):
                prev_end = _to_seconds(subtitles[j]["end_time"])
                break

        next_start = None
        for j in range(i + 1, n):
            if subtitles[j].get("start_time"):
                next_start = _to_seconds(subtitles[j]["start_time"])
                break

        if prev_end is not None and next_start is not None:
            # Evenly divide the gap
            gap = next_start - prev_end
            # Count how many consecutive missing entries need filling
            missing_count = sum(
                1 for k in range(i, n)
                if not subtitles[k].get("start_time")
                and (_to_seconds(subtitles[k - 1]["end_time"] if k > 0 else "") or -1) < 0
            )
            if missing_count < 1:
                missing_count = 1
            slot = gap / max(missing_count, 1)
            start = prev_end + slot * 0.1
            end = start + slot * 0.85
            sub["start_time"] = _from_seconds(max(0.0, start))
            sub["end_time"] = _from_seconds(max(0.0, end))
        elif prev_end is not None:
            sub["start_time"] = _from_seconds(prev_end + 0.04)
            sub["end_time"] = _from_seconds(prev_end + 2.04)
        elif next_start is not None:
            sub["start_time"] = _from_seconds(max(0.0, next_start - 2.04))
            sub["end_time"] = _from_seconds(max(0.0, next_start - 0.04))

    return subtitles
