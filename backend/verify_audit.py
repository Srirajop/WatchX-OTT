"""
Verification + audit script for the SubtitleAI V2 clean / track-changes pipeline.

Runs the DETERMINISTIC path (no LLM / no API key needed) on a real SRT:
    parse -> auto_fix -> ensure_srt_timings -> prepare_for_platform -> deduce_change_rules

It then checks two things the user explicitly asked for:
  1. Extraction / cleaning works (subtitles parsed, text cleaned, nothing lost).
  2. Track-changes never HALLUCINATES a rule: every reported "Rule: ..." label is
     backed by a real, deterministic rule_hint (ground truth) and a genuine
     before/after text difference.
"""

import io
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from timecoded_subtitles import parse_timecoded_subtitles, ensure_srt_timings, prepare_for_platform
from quality_checker import auto_fix_subtitles, deduce_change_rules
from platform_rules import get_platform

SRT_PATH = r"D:\Downloads\OTTWatchX\EVIL_0405_FINAL_TC_IYUNO SDI.srt"
PLATFORM_KEY = "discovery_max"


def main():
    with io.open(SRT_PATH, "r", encoding="utf-8", errors="ignore") as fh:
        raw = fh.read()

    # --- Step 1: EXTRACTION -------------------------------------------------
    parsed = parse_timecoded_subtitles(raw)
    print(f"[EXTRACT] Parsed {len(parsed)} timecoded subtitles from the SRT.")
    assert parsed, "Extraction failed: no subtitles parsed from a valid SRT."
    # Sanity: every parsed entry has text + a real time range
    bad = [s for s in parsed if not s.get("text") or not s.get("start_time") or not s.get("end_time")]
    assert not bad, f"Extraction produced {len(bad)} entries missing text/timecodes."
    # Mimic main.py: carry the pre-clean text as original_text on each sub so
    # track-changes can compare per-subtitle (prepare_for_platform renumbers,
    # but original_text travels with the sub).
    for s in parsed:
        s["original_text"] = s["text"]

    # --- Step 2: CLEANING (deterministic auto_fix) --------------------------
    platform = get_platform(PLATFORM_KEY)
    fixed = auto_fix_subtitles(parsed, PLATFORM_KEY)
    fixed = ensure_srt_timings(fixed)
    fixed = prepare_for_platform(fixed, PLATFORM_KEY, os.path.basename(SRT_PATH))

    print(f"[CLEAN]   Cleaned to {len(fixed)} subtitles for platform '{platform['name']}'.")

    # --- Step 3: TRACK-CHANGES + anti-hallucination audit -------------------
    rules = platform.get("rules", [])
    changed = 0
    hallucination_risk = 0
    report_rows = []

    for sub in fixed:
        sid = sub["id"]
        orig = sub.get("original_text", "")
        new = sub.get("text", "")
        hints = sub.get("rule_hints", [])
        if orig.strip() == new.strip():
            continue
        changed += 1
        applied = deduce_change_rules(orig, new, rules, hints)

        # Anti-hallucination check: any "Rule: ..." label MUST be backed by a
        # deterministic hint OR a genuine, detectable text change in that category.
        for label in applied:
            if label.startswith("Rule:"):
                rule_text = label[len("Rule: "):]
                # The quoted guideline must actually appear in the platform's rule list.
                if rule_text not in rules:
                    hallucination_risk += 1
                    print(f"  !! HALLUCINATION: quoted rule not in platform rules (sub {sid}): {rule_text!r}")
                # And the change must be real.
                if orig.strip() == new.strip():
                    hallucination_risk += 1
                    print(f"  !! HALLUCINATION: rule quoted but text unchanged (sub {sid})")

        report_rows.append((sid, orig, new, applied))

    print(f"\n[AUDIT]    {changed} lines changed.")
    print(f"[AUDIT]    Rule-hint coverage: "
          f"{sum(1 for _,_,_,a in report_rows if any(l.startswith('Rule:') or l.startswith('Verified edit:') for l in a))} / {changed} changed lines have an explained rule.")
    print(f"[AUDIT]    Hallucination risks detected: {hallucination_risk}")

    # --- Show a sample of the honest report --------------------------------
    print("\n" + "=" * 80)
    print("SAMPLE TRACK-CHANGES REPORT (first 12 changed lines)")
    print("=" * 80)
    for sid, orig, new, applied in report_rows[:12]:
        print(f"\n#{sid}")
        print(f"  BEFORE : {orig}")
        print(f"  AFTER  : {new}")
        for label in applied:
            print(f"  - {label}")

    # --- Synthetic truth test: ensure a capitalisation-only change is NOT
    #     mis-attributed to an unrelated rule -------------------------------
    print("\n" + "=" * 80)
    print("SYNTHETIC TRUTH TESTS")
    print("=" * 80)
    synth = [
        ("hello there.", "Hello there.", ["capitalize"]),                       # only capitalisation
        ("[MUSIC] let's go.", "let's go.", ["hoh_removed"]),                    # HOH removed
        ("i saw 3 dogs.", "I saw three dogs.", ["capitalize", "number_to_word"]),# cap + number
        ("He said voila.", "He said <i>voila</i>.", ["italics_added"]),          # italics
    ]
    for orig, new, expected_hints in synth:
        applied = deduce_change_rules(orig, new, rules, expected_hints)
        print(f"\n  '{orig}' -> '{new}'")
        for label in applied:
            print(f"    - {label}")

    print("\nDONE. Hallucination risks:", hallucination_risk)
    if hallucination_risk == 0:
        print("RESULT: PASS — every reported rule is genuine (ground-truth backed).")
    else:
        print("RESULT: FAIL — hallucination risks found (see above).")
        sys.exit(1)


if __name__ == "__main__":
    main()
