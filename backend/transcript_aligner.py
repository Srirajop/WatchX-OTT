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
    matched_blocks = sum(t for t, _, _ in sm.get_matching_blocks())
    coverage = matched_blocks / len(a_tokens) if a_tokens else 0.0

    # 4. Length penalty: if the window is 4× larger than the cleaned line,
    #    boost the score less (it's a vague match)
    len_ratio = len(a_tokens) / max(len(b_tokens), 1)
    len_penalty = min(1.0, len_ratio * 2.0)  # penalizes b >> a

    score = (ratio * 0.35 + jaccard * 0.30 + coverage * 0.25 + len_penalty * 0.10)
    return round(score, 4)


def align_transcription_to_script(
    whisper_subs: list[dict],   # Whisper output — has timecodes, text may be wrong
    cleaned_subs: list[dict],   # OTT script  — has correct text, timecodes unreliable
    similarity_threshold: float = ANCHOR_THRESHOLD,   # kept for API compat
) -> list[dict]:
    """
    Transfer Whisper timecodes to OTT cleaned script lines.
    The cleaned text is NEVER modified — only start_time / end_time are assigned.
    """
    if not whisper_subs or not cleaned_subs:
        return cleaned_subs

    # ── Pre-tokenize everything once ─────────────────────────────────────────
    w_tokens = [_tokens(s.get("text", "")) for s in whisper_subs]
    c_tokens = [_tokens(s.get("text", "")) for s in cleaned_subs]
    N = len(cleaned_subs)
    M = len(whisper_subs)

    # ── Build score matrix (N × M) using sliding windows of Whisper segs ─────
    # score_matrix[i][j] = best similarity between cleaned_subs[i] and a
    # window of Whisper segments starting at j.
    # best_window[i][j]  = window size that produced that score.
    score_matrix = [[0.0] * M for _ in range(N)]
    best_window  = [[1]    * M for _ in range(N)]

    for i in range(N):
        ct = c_tokens[i]
        if not ct:
            continue
        for j in range(M):
            window_tokens: list[str] = []
            best_s = 0.0
            best_w = 1
            for w in range(1, MAX_WINDOW + 1):
                if j + w - 1 >= M:
                    break
                window_tokens = window_tokens + w_tokens[j + w - 1]
                s = _similarity(ct, window_tokens)
                if s > best_s:
                    best_s = s
                    best_w = w
            score_matrix[i][j] = best_s
            best_window[i][j]  = best_w

    # ── Monotonic DP alignment ────────────────────────────────────────────────
    # dp[i][j] = best total score for aligning cleaned[0..i] to whisper[0..j]
    # We want the assignment that:
    #   a) is strictly monotonically increasing in j (no going backwards in time)
    #   b) maximises the total similarity
    #
    # State: dp[i] = (best_score, best_whisper_end_idx, backtrack)
    INF = float('-inf')
    # dp_score[i] = best cumulative score ending with cleaned[i] matched somewhere
    dp_score    = [INF] * N
    dp_w_start  = [-1]  * N   # which whisper segment index the window starts at
    dp_w_end    = [-1]  * N   # which whisper segment index the window ends at
    dp_prev     = [-1]  * N   # previous cleaned line index in the chain

    for i in range(N):
        ct = c_tokens[i]
        if not ct:
            # empty cleaned line — skip and inherit previous position
            dp_score[i] = dp_score[i-1] if i > 0 else 0.0
            dp_w_start[i] = dp_w_start[i-1] if i > 0 else -1
            dp_w_end[i] = dp_w_end[i-1] if i > 0 else -1
            dp_prev[i]  = i - 1
            continue

        # Determine search range in Whisper
        # We allow skipping Whisper segments (e.g. hallucinations) but penalize it
        min_j = 0 if i == 0 else max(0, dp_w_end[i-1])      # must be >= previous end
        max_j = min(M, min_j + MAX_LOOKAHEAD)

        best_s   = INF
        best_j   = min_j
        prev_cum = dp_score[i-1] if i > 0 else 0.0
        if prev_cum == INF:
            prev_cum = 0.0

        for j in range(min_j, max_j):
            s = score_matrix[i][j]
            # Penalize jumping too far ahead in the Whisper transcript to prevent
            # coincidental noise matches 50 lines later from outscoring the true match.
            gap_penalty = (j - min_j) * 0.08
            cum = prev_cum + s - gap_penalty
            if cum > best_s:
                best_s = cum
                best_j = j

        w = best_window[i][best_j] if best_j < M else 1
        dp_score[i] = best_s
        dp_w_start[i] = best_j
        dp_w_end[i] = best_j + w - 1      # inclusive end of the whisper window
        dp_prev[i]  = i - 1

    # ── Build result ──────────────────────────────────────────────────────────
    result: list[dict] = []

    for i, cleaned_sub in enumerate(cleaned_subs):
        item = dict(cleaned_sub)

        # Lines that already have good timecodes — leave them alone
        if cleaned_sub.get("start_time") and cleaned_sub.get("end_time"):
            result.append(item)
            continue

        # Skip empty
        if not c_tokens[i]:
            item.setdefault("start_time", "")
            item.setdefault("end_time", "")
            result.append(item)
            continue

        w_start = dp_w_start[i]
        w_end = dp_w_end[i]
        if w_end < 0 or w_end >= M or w_start < 0:
            # No match found
            item["start_time"] = ""
            item["end_time"]   = ""
            item["flagged"]    = True
            item["flag_reason"] = "Could not align to Whisper transcript — will be interpolated"
            item["align_score"] = 0.0
            result.append(item)
            continue

        j_s = w_start
        raw_score = score_matrix[i][j_s]

        start_whisper = whisper_subs[j_s]
        end_whisper   = whisper_subs[w_end]

        item["start_time"]   = start_whisper.get("start_time", "")
        item["end_time"]     = end_whisper.get("end_time", "")
        item["align_score"]  = raw_score
        item["align_source"] = f"whisper_seg_{j_s+1}-{w_end+1}"

        if raw_score >= ANCHOR_THRESHOLD:
            # High confidence — clean match
            item.setdefault("flagged", False)
            item.setdefault("flag_reason", "")
        elif raw_score >= ACCEPT_THRESHOLD:
            # Low confidence but accepted — flag for subtitler review
            item["flagged"]    = True
            item["flag_reason"] = f"Low-confidence alignment (score: {raw_score:.2f}) — please verify timecode"
        else:
            # Very low confidence — timecode may be wrong
            item["flagged"]    = True
            item["flag_reason"] = f"Uncertain alignment (score: {raw_score:.2f}) — timecode interpolated from neighbours"
            item["start_time"] = ""
            item["end_time"]   = ""

        result.append(item)

    # ── Interpolate timecodes for unmatched lines ─────────────────────────────
    result = _interpolate_missing_timecodes(result)

    # ── Re-index ──────────────────────────────────────────────────────────────
    for idx, sub in enumerate(result, start=1):
        sub["id"] = idx

    return result


def _interpolate_missing_timecodes(subtitles: list[dict]) -> list[dict]:
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
                sub["end_time"]   = _from_seconds(t + 2.0)
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
            subtitles[gi]["end_time"]   = _from_seconds(max(0.0, t_end))

    return subtitles
