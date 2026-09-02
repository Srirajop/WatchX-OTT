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
import os

from timecoded_subtitles import _to_seconds, _from_seconds


# A match below this is not reliable enough to assign a real timestamp.
ACCEPT_THRESHOLD = 0.28
ANCHOR_THRESHOLD = 0.62
# How many Whisper tokens we may skip forward when the script line's words are
# not at the exact cursor (e.g. Whisper inserted filler the script never had).
_MAX_SKIP_TOKENS = 12
# Upper bound on how far ahead we search for a line's Whisper run.
_MAX_LOOKAHEAD_TOKENS = 400
# Upper bound on a single line's Whisper run length (in tokens).
_MAX_RUN_TOKENS = 80
_MAX_SPLIT_WORDS = 24
_MAX_MERGED_CUES = 5
_MAX_CANDIDATES_PER_LINE = 30
_MAX_DP_STATES = 150
MIN_MANUAL_CUE_SECONDS = 1.0  # minimum slot reserved for each gap-filled line

_STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "of",
    "is", "it", "i", "we", "he", "she", "they", "you", "was", "were",
    "be", "are", "for",
}


def _normalize(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    text = re.sub(r"\b(can't|cannot)\b", "cannot", text, flags=re.I)
    text = re.sub(r"\b(won't)\b", "will not", text, flags=re.I)
    text = re.sub(r"\b(I'm)\b", "i am", text, flags=re.I)
    text = re.sub(r"\b(you're)\b", "you are", text, flags=re.I)
    text = re.sub(r"\b(it's)\b", "it is", text, flags=re.I)
    text = re.sub(r"\b(colour)\b", "color", text, flags=re.I)
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
    # Character similarity catches spelling errors and inflections without
    # assuming a particular language or translation pair.
    char_ratio = difflib.SequenceMatcher(None, " ".join(a_tokens), " ".join(b_tokens), autojunk=False).ratio()
    return round(0.30 * coverage + 0.28 * content_overlap + 0.17 * ratio +
                 0.15 * char_ratio + 0.10 * length_ratio, 4)


def _build_timeline(whisper_subs: list[dict]) -> list[dict]:
    """Build an ordered word timeline, preferring stable-ts word timings."""
    timeline = []
    for whisper_index, sub in enumerate(whisper_subs):
        start = _to_seconds(sub.get("start_time", ""))
        end = _to_seconds(sub.get("end_time", ""))
        if start is None or end is None or end <= start:
            continue
        word_items = sub.get("words") or []
        toks = [_normalize(w.get("word", "")) for w in word_items]
        toks = [t for t in toks if t]
        if word_items and toks:
            for word, token in zip(word_items, toks):
                ws = float(word.get("start", start)); we = float(word.get("end", end))
                timeline.append({"token": token, "start": max(start, ws), "end": min(end, max(ws, we)),
                                 "confidence": word.get("confidence"), "source_id": whisper_index,
                                 "source_text": sub.get("text", "")})
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
                "source_id": whisper_index,
                "source_text": sub.get("text", ""),
            })
    return timeline


def _build_cue_index(timeline: list[dict]) -> list[dict]:
    """Pre-group timeline tokens by their Whisper source cue for fast lookup."""
    cues: dict[int, dict] = {}
    for tok in timeline:
        cid = tok["source_id"]
        if cid not in cues:
            cues[cid] = {"source_id": cid, "tokens": [], "start_tok": None, "end_tok": None}
        entry = cues[cid]
        entry["tokens"].append(tok["token"])
    # Also record first/last token positions in the flat timeline
    for pos, tok in enumerate(timeline):
        cid = tok["source_id"]
        entry = cues[cid]
        if entry["start_tok"] is None:
            entry["start_tok"] = pos
        entry["end_tok"] = pos + 1
    return [cues[k] for k in sorted(cues)]


def _dtw_semantic_groups(scores):
    """Return globally ordered cue groups for each client line.

    This is a Needleman-Wunsch/DTW-style alignment over the multilingual
    similarity matrix. Skip transitions absorb extra/missing subtitle cues;
    match transitions may be repeated so one client cue can cover several
    reference cues and vice versa.
    """
    if scores is None or not getattr(scores, "shape", None):
        return None
    cue_count, line_count = scores.shape
    if not cue_count or not line_count:
        return None
    dp = [[-10**9] * (line_count + 1) for _ in range(cue_count + 1)]
    back = [[None] * (line_count + 1) for _ in range(cue_count + 1)]
    dp[0][0] = 0.0
    for c in range(cue_count + 1):
        for l in range(line_count + 1):
            v = dp[c][l]
            if v <= -10**8:
                continue
            if c < cue_count and v - 0.05 > dp[c + 1][l]:
                dp[c + 1][l] = v - 0.05; back[c + 1][l] = (c, l, "cue_skip")
            if l < line_count and v - 0.12 > dp[c][l + 1]:
                dp[c][l + 1] = v - 0.12; back[c][l + 1] = (c, l, "line_skip")
            if c < cue_count and l < line_count:
                score = float(scores[c, l])
                if v + score > dp[c + 1][l + 1]:
                    dp[c + 1][l + 1] = v + score; back[c + 1][l + 1] = (c, l, "match")
    groups = [[] for _ in range(line_count)]
    c, l = cue_count, line_count
    while c or l:
        step = back[c][l]
        if step is None:
            break
        pc, pl, kind = step
        if kind == "match" and l > 0:
            groups[l - 1].append(c - 1)
        c, l = pc, pl
    return [sorted(g) for g in groups]


def _assign_ordered(timeline: list[dict], script_lines: list[list[str]], semantic_matrix=None, progress_callback=None) -> list:
    """Globally align script lines to transcript spans with DP.

    Candidates are generated at the Whisper-cue level (one similarity call per
    cue) instead of the brute-force token-span level, reducing complexity from
    O(lines × window × max_span) to O(lines × nearby_cues).
    """
    n = len(script_lines)
    cue_list = _build_cue_index(timeline)
    num_cues = len(cue_list)
    semantic_groups = _dtw_semantic_groups(semantic_matrix)

    candidates = []
    for i, toks in enumerate(script_lines):
        line_candidates = []
        if toks:
            # Search within a window of cues centred on the expected position
            if n > 1:
                expected_cue = int(i * num_cues / n)
                half_win = min(80, max(20, num_cues // 4))
                c_start = max(0, expected_cue - half_win)
                c_end = min(num_cues, expected_cue + half_win + 1)
            else:
                c_start, c_end = 0, num_cues

            # Fast path: exact normalized token match against a single cue
            for ci in range(c_start, c_end):
                cue = cue_list[ci]
                if cue["tokens"] == toks:
                    line_candidates.append((1.0, cue["start_tok"], cue["end_tok"]))
            if line_candidates:
                # Exact match found — use it directly, no need to search further
                candidates.append(line_candidates[:_MAX_CANDIDATES_PER_LINE])
                if progress_callback and (i == 0 or (i + 1) % 10 == 0 or i + 1 == n):
                    try:
                        progress_callback(i + 1, n)
                    except Exception:
                        pass
                continue

            # Single-cue fuzzy candidates — use a LOWER threshold here because
            # cue-level similarity naturally scores lower when cue text is longer
            # or shorter than the script line.
            CUE_THRESHOLD = max(0.20, ACCEPT_THRESHOLD - 0.08)
            for ci in range(c_start, c_end):
                cue = cue_list[ci]
                score = _similarity(cue["tokens"], toks)
                if score >= CUE_THRESHOLD:
                    line_candidates.append((score, cue["start_tok"], cue["end_tok"]))

                # One Whisper cue may contain several client cues. Enumerate
                # bounded word sub-spans so Stable-ts word timings can split it
                # without assigning the whole cue to the first line.
                cue_len = len(cue["tokens"])
                if cue_len > 1:
                    for local_start in range(cue_len):
                        local_end = min(cue_len, local_start + _MAX_SPLIT_WORDS)
                        for local_stop in range(local_start + 1, local_end + 1):
                            if local_start == 0 and local_stop == cue_len:
                                continue
                            span_score = _similarity(cue["tokens"][local_start:local_stop], toks)
                            if span_score >= CUE_THRESHOLD:
                                line_candidates.append((
                                    span_score,
                                    cue["start_tok"] + local_start,
                                    cue["start_tok"] + local_stop,
                                ))

            # Adjacent cue merges handle one client line split over multiple
            # Whisper cues. Keep the candidate width bounded for long files.
            for ci in range(c_start, min(c_end, c_start + 40)):
                merged_tokens = []
                for width in range(1, _MAX_MERGED_CUES + 1):
                    end_ci = ci + width
                    if end_ci > len(cue_list) or end_ci > c_end + 1:
                        break
                    merged_tokens.extend(cue_list[ci + width - 1]["tokens"])
                    if width == 1:
                        continue
                    score = _similarity(merged_tokens, toks)
                    if score >= max(0.18, CUE_THRESHOLD - 0.05):
                        line_candidates.append((
                            score, cue_list[ci]["start_tok"], cue_list[end_ci - 1]["end_tok"]
                        ))

            # Semantic candidates (cross-language support)
            if semantic_matrix is not None:
                for cue_index in range(semantic_matrix.shape[0]):
                    sim = float(semantic_matrix[cue_index, i])
                    if sim < 0.30:
                        continue
                    cue = cue_list[cue_index] if cue_index < len(cue_list) else None
                    if not cue:
                        continue
                    lexical = _similarity(cue["tokens"], toks)
                    line_candidates.append((max(lexical, min(0.99, (sim + 1) / 2)),
                                            cue["start_tok"], cue["end_tok"]))
                if semantic_groups and i < len(semantic_groups) and semantic_groups[i]:
                    group = [x for x in semantic_groups[i] if x < len(cue_list)]
                    if group:
                        first, last = cue_list[min(group)], cue_list[max(group)]
                        score = sum(float(semantic_matrix[x, i]) for x in group) / len(group)
                        line_candidates.append((min(0.99, max(0.0, (score + 1) / 2)),
                                                first["start_tok"], last["end_tok"]))

        line_candidates.sort(key=lambda x: (x[0], -(x[2] - x[1])), reverse=True)
        candidates.append(line_candidates[:_MAX_CANDIDATES_PER_LINE])
        if progress_callback and (i == 0 or (i + 1) % 10 == 0 or i + 1 == n):
            try:
                progress_callback(i + 1, n)
            except Exception:
                pass

    # ── Sparse DP with backpointer table (no list copying) ──────────────────
    # best_at[pos] = (score_value, best_prev_pos, best_action)
    # backtrack[(line_idx, pos)] = (prev_pos, action)  for reconstruction
    best_at = {0: 0.0}           # token-position -> best cumulative value
    prev_at = {0: (None, None)}  # token-position -> (came_from_pos, action)
    backtrack = {}               # (line_idx+1, dest_pos) -> (src_pos, action)

    for i in range(n):
        toks_i = script_lines[i]
        next_best: dict = {}   # dest_pos -> best_value
        next_prev: dict = {}   # dest_pos -> (src_pos, action)

        for pos, val in best_at.items():
            # Option A: skip this line (unmatched)
            penalty = 0.18 if toks_i else 0.0
            new_val = val - penalty
            if pos not in next_best or new_val > next_best[pos]:
                next_best[pos] = new_val
                next_prev[pos] = (pos, None)

            # Option B: assign a candidate span
            for score, j, k in candidates[i]:
                if j < pos:
                    continue
                skip_pen = min(0.25, (j - pos) * 0.002)
                new_val = val + score - skip_pen
                if k not in next_best or new_val > next_best[k]:
                    next_best[k] = new_val
                    next_prev[k] = (pos, (score, j, k))

        # Prune to keep the top MAX_DP_STATES positions
        if len(next_best) > _MAX_DP_STATES:
            keep = sorted(next_best, key=lambda p: next_best[p], reverse=True)[:_MAX_DP_STATES]
            next_best = {p: next_best[p] for p in keep}
            next_prev = {p: next_prev[p] for p in keep}

        # Store backpointers for reconstruction
        for dest_pos, (src_pos, action) in next_prev.items():
            if dest_pos in next_best:            # only for surviving states
                backtrack[(i + 1, dest_pos)] = (src_pos, action)

        best_at = next_best
        prev_at = next_prev

    if not best_at:
        return [None] * n

    # Pick the best terminal position
    curr_pos = max(best_at, key=lambda p: best_at[p])

    # Trace back through backtrack to recover per-line assignments
    path = [None] * n
    for i in range(n, 0, -1):
        key = (i, curr_pos)
        if key not in backtrack:
            # Backtrack broken — fill remaining as unmatched
            break
        src_pos, action = backtrack[key]
        path[i - 1] = action
        curr_pos = src_pos

    return path


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
    progress_callback=None,
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

    def _cb(step, done=0, total=0):
        if progress_callback:
            try:
                progress_callback(step, done, total)
            except Exception:
                pass

    timeline = _build_timeline(whisper_subs)
    bridge_result = None
    try:
        from bridge_translator import build_bridge_texts
        _cb("bridge", 0, len(cleaned_subs))
        bridge_result = build_bridge_texts(
            whisper_subs,
            cleaned_subs,
            progress_callback=lambda done, total: _cb("bridge", done, total),
        )
        _cb("bridge", len(cleaned_subs), len(cleaned_subs))
    except Exception as exc:
        # A missing local language package must not damage same-language
        # alignment. The semantic fallback remains available when prepared;
        # the API/UI reports the setup requirement separately.
        print(f"[align] local language bridge unavailable: {exc}")
    matching_texts = bridge_result.texts if bridge_result and bridge_result.used else [sub.get("text", "") for sub in cleaned_subs]
    script_lines = [_tokens(text) for text in matching_texts]

    _cb("lexical", 0, len(script_lines))
    semantic_matrix = None
    # Avoid loading the embedding model for ordinary same-language jobs when
    # lexical/global alignment already resolves the script.
    lexical_assignments = _assign_ordered(
        timeline,
        script_lines,
        progress_callback=lambda done, total: _cb("lexical", done, total),
    )
    _cb("lexical", len(script_lines), len(script_lines))
    try:
        from semantic_matcher import multilingual_scores
        from semantic_matcher import model_status
        if not model_status()["cached"]:
            raise RuntimeError("Multilingual model is not prepared. Open Setup and prepare the language model.")
        cue_texts = []
        seen = set()
        for item in timeline:
            if item["source_id"] not in seen:
                cue_texts.append(item.get("source_text", "")); seen.add(item["source_id"])
        unresolved_ratio = sum(x is None for x in lexical_assignments) / max(1, len(script_lines))
        if any(cue_texts) and unresolved_ratio >= 0.20:
            _cb("semantic", 0, len(cue_texts))
            semantic_matrix = multilingual_scores(cue_texts, matching_texts)
            _cb("semantic", len(cue_texts), len(cue_texts))
    except Exception as exc:
        print(f"[align] semantic matching skipped: {exc}")
    _cb("dp")
    assignments = (
        _assign_ordered(
            timeline,
            script_lines,
            semantic_matrix,
            progress_callback=lambda done, total: _cb("semantic", done, total),
        )
        if semantic_matrix is not None
        else lexical_assignments
    )

    result = []
    for index, script_sub in enumerate(cleaned_subs):
        item = dict(script_sub)
        item["id"] = index + 1
        item["client_index"] = index
        item["client_text"] = item.get("text", "")
        item["start"] = ""
        item["end"] = ""
        item["align_mode"] = mode
        item["align_method"] = ""
        item.setdefault("align_source", "")
        item.setdefault("manual_placement", False)
        item["bridge_used"] = bool(bridge_result and bridge_result.used)
        if bridge_result:
            item["bridge_source_language"] = bridge_result.source_language
            item["bridge_target_language"] = bridge_result.target_language

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
            item["matched_whisper_indices"] = []
            item["match_method"] = "none"
            item["confidence"] = 0.0
            item["status"] = "UNMATCHED"
            item["flag_reason"] = "No verified transcript span matched"
            result.append(item)
            continue

        score, span_start, span_end = asg
        start, end = timeline[span_start]["start"], timeline[span_end - 1]["end"]
        if preserve and original_duration is not None:
            end = start + original_duration
        item["start_time"] = _from_seconds(start)
        item["end_time"] = _from_seconds(max(end, start + 0.04))
        item["start"] = item["start_time"]
        item["end"] = item["end_time"]
        item["align_score"] = round(score, 4)
        item["matched_whisper_indices"] = sorted({timeline[x]["source_id"] for x in range(span_start, span_end)})
        item["match_method"] = "bridge_global_sequence" if bridge_result and bridge_result.used else "global_sequence"
        item["confidence"] = round(score, 4)
        item["status"] = "AUTO_MAPPED" if score >= similarity_threshold else "AMBIGUOUS"
        item["flagged"] = score < ANCHOR_THRESHOLD
        item["align_source"] = "whisper"
        item["align_method"] = "whisper"
        item["flag_reason"] = "Partial transcript match; verify timing" if item["flagged"] else ""
        if item["status"] == "AMBIGUOUS":
            item["start_time"] = ""
            item["end_time"] = ""
            item["start"] = ""
            item["end"] = ""
        result.append(item)

    # Unmatched dialogue remains explicitly unresolved.  Never invent a timing
    # slot: the UI can route only these genuinely ambiguous lines to review.
    # Never manufacture timings for unresolved client dialogue.

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
