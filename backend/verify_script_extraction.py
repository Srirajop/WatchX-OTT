"""Regression checks for the supplied production scripts.

Run from ``backend`` with: ``python verify_script_extraction.py``.
The test deliberately uses the normal native-text path.  OCR is tested as a
fallback elsewhere; it must not be appended to an already-readable script.
"""

from pathlib import Path

from file_reader import read_file
from timecoded_subtitles import parse_timecoded_subtitles


ROOT = Path(r"D:\Downloads\OTTWatchX\scripts_unzipped\All Possible Current scripts\ALL Script")
MIN_TIMED_CUES = {
    "Juno - CCSL - Reel 1AB.doc": 180,
    "EVIL_0405_FINAL_TC_IYUNO SDI.pdf": 700,
    "Late Night with the Devil - CCSL[2] (1).pdf": 1_000,
    "Tiny Toons - Eps 19- Nightmare On Toon Street Part One-A14.15746.pdf": 300,
}


def main() -> None:
    failures: list[str] = []
    for path in sorted(ROOT.iterdir()):
        result = read_file(path.read_bytes(), path.name)
        raw_text = result["raw_text"]
        cues = parse_timecoded_subtitles(raw_text)

        if not raw_text.strip():
            failures.append(f"{path.name}: no text extracted")
            continue
        if "=== OCR EXTRACTED CONTENT ===" in raw_text:
            failures.append(f"{path.name}: OCR duplicated readable native text")

        minimum = MIN_TIMED_CUES.get(path.name)
        if minimum is not None and len(cues) < minimum:
            failures.append(
                f"{path.name}: expected at least {minimum} timecoded cues, got {len(cues)}"
            )

        print(f"PASS {path.name}: {result['format']} / {result['structure']} / {len(cues)} timed cues")

    # Juno is the key regression: CCSL explanatory notes must not be delivered.
    juno = ROOT / "Juno - CCSL - Reel 1AB.doc"
    juno_cues = parse_timecoded_subtitles(read_file(juno.read_bytes(), juno.name)["raw_text"])
    juno_text = "\n".join(cue["text"] for cue in juno_cues)
    for leaked_note in ("Bleeker’s nickname for Juno", "This is the third test Juno has purchased today"):
        if leaked_note in juno_text:
            failures.append(f"Juno: explanatory note leaked into subtitles: {leaked_note}")

    if failures:
        raise AssertionError("\n".join(failures))

    print(f"Verified {len(list(ROOT.iterdir()))} supplied scripts successfully.")


if __name__ == "__main__":
    main()
