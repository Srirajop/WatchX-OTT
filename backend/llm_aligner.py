"""AI refinement of the script->Whisper alignment using Groq (openai/gpt-oss-20b by default).

The deterministic alignment in transcript_aligner.py already produces a
video-synced result.  This module is a *targeted* second pass: it asks the LLM
to re-time only the weak lines (flagged / gap-filled / unmatched), choosing a
start and end timecode from the actual Whisper cue pool around that line.  The
LLM is never allowed to invent a timecode outside the available cues, so the
result stays synced.  If Groq is unavailable or a call fails, the deterministic
result is returned unchanged.
"""

import json
import re
import time

from timecoded_subtitles import _to_seconds, _from_seconds


_SYSTEM = (
    "You are a multilingual subtitle alignment selector. The client dialogue "
    "may be in a different language from the speech-recognition cues. Compare "
    "meaning, translation, order, and context. Return STRICT JSON only with "
    "integer cue_start and cue_end fields, where both numbers are the local "
    "cue-list indexes. Choose only supplied cues; never invent times, text, or "
    "a translation. cue_end is inclusive. Example: "
    "{\"cue_start\":2,\"cue_end\":3,\"confidence\":0.84}."
)

# This is an explicit manual-placement action.  It may work through a larger
# set of unresolved lines, but remains bounded so a failed provider cannot
# leave the UI waiting forever.
MAX_AI_REFINEMENTS = int(__import__("os").getenv("WATCHX_MAX_AI_REFINEMENTS", "900"))
AI_REFINEMENT_TIME_BUDGET_SECONDS = float(__import__("os").getenv("WATCHX_AI_TIME_BUDGET", "1800"))
AI_REQUEST_INTERVAL_SECONDS = float(__import__("os").getenv("WATCHX_AI_REQUEST_INTERVAL", "2.2"))


def _whisper_cues(whisper_subs: list[dict]) -> list[dict]:
    cues = []
    for original_index, sub in enumerate(whisper_subs):
        start = _to_seconds(sub.get("start_time", ""))
        end = _to_seconds(sub.get("end_time", ""))
        if start is None or end is None or end <= start:
            continue
        cues.append({"index": original_index, "start": start, "end": end, "text": sub.get("text", "")})
    return cues


def _tc_to_str(seconds: float) -> str:
    return _from_seconds(seconds)


def _context_cues(cues: list[dict], prev_end, next_start, line_index=None, line_total=None) -> list[dict]:
    """Pick the Whisper cues surrounding the gap this weak line falls into."""
    if prev_end is None:
        prev_end = -1e9
    if next_start is None:
        next_start = 1e9
    # Everything between the previous aligned line's end and the next aligned
    # line's start, plus a small buffer on each side.
    window = [
        c for c in cues
        if c["end"] >= prev_end - 1.0 and c["start"] <= next_start + 1.0
    ]
    if not window or len(window) > 24:
        if line_index is not None and line_total:
            centre = int(line_index * len(cues) / max(1, line_total))
            lo = max(0, centre - 8); hi = min(len(cues), centre + 9)
            window = cues[lo:hi]
    if not window:
        # Fall back to cues nearest the gap centre.
        centre = (prev_end + next_start) / 2 if next_start < 1e8 else prev_end
        window = sorted(cues, key=lambda c: abs((c["start"] + c["end"]) / 2 - centre))[:12]
    return window


def refine_alignment_with_llm(
    whisper_subs: list[dict],
    aligned_subs: list[dict],
    mode: str = "ai",
    progress_callback=None,
) -> list[dict]:
    from cleaner import _get_client_and_model

    cues = _whisper_cues(whisper_subs)
    if not cues:
        return aligned_subs

    try:
        client, model, _ = _get_client_and_model()
    except Exception as exc:
        print(f"[llm_align] Groq unavailable, skipping AI pass: {exc}")
        return aligned_subs

    weak = [
        i for i, s in enumerate(aligned_subs)
        if (not s.get("start_time")) or s.get("flagged") or s.get("manual_placement")
    ]
    if not weak:
        return aligned_subs

    # Pre-compute the time boundaries of the good (confidently aligned) lines so
    # each weak line can be given only the cues around its true position.
    good_bounds = []
    for i, s in enumerate(aligned_subs):
        if s.get("start_time") and not s.get("flagged") and not s.get("manual_placement"):
            good_bounds.append((i, _to_seconds(s["start_time"]), _to_seconds(s["end_time"])))

    result = [dict(s) for s in aligned_subs]
    preserve_duration = mode == "preserve_duration"
    started_at = time.monotonic()
    targets = weak[:MAX_AI_REFINEMENTS]
    for position, idx in enumerate(targets, start=1):
        if progress_callback:
            progress_callback(position - 1, len(targets), result, result[idx])
        remaining = AI_REFINEMENT_TIME_BUDGET_SECONDS - (time.monotonic() - started_at)
        if remaining <= 0:
            print("[llm_align] AI review time budget reached; returning partial review.")
            break
        sub = result[idx]
        existing_start = _to_seconds(sub.get("start_time", ""))
        existing_end = _to_seconds(sub.get("end_time", ""))
        existing_duration = (
            existing_end - existing_start
            if existing_start is not None and existing_end is not None and existing_end > existing_start
            else None
        )
        # Previous/next good boundaries relative to this weak line.
        prev_end = None
        next_start = None
        for gi, gs, ge in good_bounds:
            if gi < idx:
                prev_end = ge
            elif gi > idx and next_start is None:
                next_start = gs
        ctx = _context_cues(cues, prev_end, next_start, idx, len(aligned_subs))
        if not ctx:
            continue

        cue_list = "\n".join(
            f'{n}. {_tc_to_str(c["start"])} --> {_tc_to_str(c["end"])} | {c["text"]}'
            for n, c in enumerate(ctx)
        )
        user = (
            f"TIMED CUES (choose start/end from these only):\n{cue_list}\n\n"
            f'SCRIPT LINE #{idx + 1}: {sub.get("text", "")}\n\n'
            "Return only JSON with cue_start, cue_end, and confidence."
        )

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": user},
                ],
                temperature=0.0,
                max_tokens=256,
                response_format={"type": "json_object"},
                timeout=min(8.0, remaining),
            )
            content = (response.choices[0].message.content or "").strip()
        except Exception as exc:
            err = str(exc).lower()
            if "429" in err or "rate limit" in err:
                print("[llm_align] Rate limited — stopping AI pass.")
                break
            print(f"[llm_align] call failed for line {idx + 1}: {exc}")
            time.sleep(1.0)
            continue

        # Stay below the documented free-tier request rate. A 508-line file
        # may take several minutes, but it will progress instead of flooding
        # Groq and silently abandoning the remainder.
        if position < len(targets):
            time.sleep(AI_REQUEST_INTERVAL_SECONDS)

        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            continue
        try:
            parsed = json.loads(match.group())
        except Exception:
            continue

        cue_start = parsed.get("cue_start", parsed.get("start_index"))
        cue_end = parsed.get("cue_end", parsed.get("end_index"))
        try:
            model_confidence = float(parsed.get("confidence", 0.0))
        except (TypeError, ValueError):
            model_confidence = 0.0
        try:
            cue_start = int(cue_start); cue_end = int(cue_end)
        except (TypeError, ValueError):
            cue_start = cue_end = -1
        if cue_start < 0 or cue_end < cue_start or cue_end >= len(ctx):
            # Backward-compatible parsing for an older model response that
            # returned exact supplied timecodes instead of indexes.
            start = _to_seconds(parsed.get("start", parsed.get("start_time", "")))
            end = _to_seconds(parsed.get("end", parsed.get("end_time", "")))
            if start is None or end is None:
                continue
            selected = [c for c in ctx if abs(c["start"] - start) < 0.01 and abs(c["end"] - end) < 0.01]
            if not selected:
                continue
            start, end = selected[0]["start"], selected[-1]["end"]
        else:
            start = ctx[cue_start]["start"]
            end = ctx[cue_end]["end"]
        # A selector response without an explicit positive confidence is not
        # evidence strong enough to turn an unresolved line into a timestamp.
        # The model may choose cues, but it cannot override this safety gate.
        if model_confidence < 0.50:
            continue
        if start is None or end is None or end <= start:
            continue
        # Constrain the chosen timecodes to the surrounding cue window so the LLM
        # cannot drift the line out of sync.
        lo = min(c["start"] for c in ctx)
        hi = max(c["end"] for c in ctx)
        if start < lo - 0.5 or end > hi + 0.5:
            continue

        if preserve_duration and existing_duration is not None:
            end = start + existing_duration
        sub["start_time"] = _tc_to_str(start)
        sub["end_time"] = _tc_to_str(end)
        sub["start"] = sub["start_time"]
        sub["end"] = sub["end_time"]
        sub["matched_whisper_indices"] = [c["index"] for c in ctx[cue_start:cue_end + 1]] if cue_start >= 0 else [c["index"] for c in selected]
        sub["match_method"] = "groq_candidate"
        sub["confidence"] = round(model_confidence, 4)
        sub["align_score"] = round(model_confidence, 4)
        sub["status"] = "AUTO_MAPPED"
        sub["flagged"] = False
        sub["flag_reason"] = ""
        sub["manual_placement"] = False
        sub["align_source"] = "llm_whisper"
        sub["align_method"] = "ai"
        good_bounds.append((idx, start, end))

    if progress_callback:
        progress_callback(len(targets), len(targets), result, None)
    return result
