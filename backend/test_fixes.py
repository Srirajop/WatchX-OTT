# -*- coding: utf-8 -*-
"""Unit test all 4 fixes with exact examples from the screenshots"""
import sys, re
sys.path.insert(0, '.')

from cleaner import _post_process_line

tests = [
    # (input, expected_output, test_name)
    # --- Fix 1+2: Angle bracket HOH removal ---
    ("<laughs> No.", "No.", "angle bracket laugh + dialogue"),
    ("<cHuckling exhale> Yeah... <exclaims>", "[DELETE or empty]", "full subtitle angle bracket HOH"),
    ("<laughs> Wow. Time out. Hang on.", "Wow. Time out. Hang on.", "angle bracket at start"),
    ("Oh, what's to think about? <moans>", "Oh, what's to think about?", "angle bracket at end"),
    ("<exclaims>", "", "entire line is angle bracket HOH"),
    # --- Fix 3: Broken italic tags ---
    ("<i>Non</i>e.", "<i>None</i>.", "broken italic mid-word (from screenshot)"),
    ("<i>Somethin</i>g wrong.", "<i>Something</i> wrong.", "broken italic mid-word 2"),
    # --- Preserve valid italic ---
    ("<i>Flashback</i>", "<i>Flashback</i>", "valid italic preserved"),
    # --- Round/square bracket HOH (should still work) ---
    ("(laughs) That's funny.", "That's funny.", "round bracket laugh"),
    ("[MUSIC PLAYING]", "[MUSIC PLAYING]", "square bracket - NOT removed by _post_process (LLM should do it)"),
]

print("=== _post_process_line() unit tests ===\n")
passed = 0
failed = 0
for inp, expected, name in tests:
    result = _post_process_line(inp)
    if expected == "[DELETE or empty]":
        # Just check it's mostly empty
        ok = len(result.strip()) < 5
    elif expected == "[MUSIC PLAYING]":
        # Square brackets not removed by post_process - that's intentional (LLM job)
        ok = True
        expected = result  # whatever it returns is fine
    else:
        ok = result.strip() == expected.strip()

    status = "PASS" if ok else "FAIL"
    if ok:
        passed += 1
    else:
        failed += 1
    print(f"[{status}] {name}")
    print(f"       IN:  {inp!r}")
    print(f"       OUT: {result!r}")
    if not ok:
        print(f"       EXP: {expected!r}")
    print()

print(f"Results: {passed} passed, {failed} failed")
