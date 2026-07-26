# text_utils.py — Shared subtitle text helpers
# Anti-hallucination utilities: deterministic line splitting and sentence case.

import re
from typing import List

_TAG_RE = re.compile(r"<[^>]+>")


def visible_len(text: str) -> int:
    """Character count excluding SRT/HTML tags."""
    return len(_TAG_RE.sub("", text))


def _tiny(text: str, threshold: int = 6) -> bool:
    return visible_len(text.strip()) < threshold


def smart_wrap(text: str, max_chars: int, overflow: int = 3) -> List[str]:
    """
    Wrap `text` into lines, each no longer than `max_chars` visible characters.

    Unlike greedy wrapping, this routine:
      - prefers natural boundaries (sentence ends, clauses, commas, conjunctions)
        over mid-phrase breaks,
      - avoids single-word orphan tails by allowing a small `overflow` (default 3)
        rather than leaving a lone word on its own line,
      - preserves existing line breaks and HTML/SRT tags.

    If a segment is genuinely too long for a reasonable split, it is returned
    as-is; the QC engine flags it for human review.
    """
    if not text or not text.strip():
        return []

    lines = []
    for segment in text.split("\n"):
        segment = segment.strip()
        if not segment:
            continue
        if visible_len(segment) <= max_chars:
            lines.append(segment)
            continue
        lines.extend(_split_segment(segment, max_chars, overflow))
    return lines


def _split_segment(segment: str, max_chars: int, overflow: int) -> List[str]:
    """Recursively split a single text segment at the best natural boundary."""
    segment = segment.strip()
    vlen = visible_len(segment)

    # Fits with allowed overflow -> done.
    if vlen <= max_chars + overflow:
        return [segment]

    candidates = []
    seen = set()

    def add(pos: int, kind: str):
        if pos <= 0 or pos >= len(segment):
            return
        key = (pos, kind)
        if key in seen:
            return
        seen.add(key)
        left = segment[:pos].rstrip()
        right = segment[pos:].lstrip()
        if not left or not right:
            return
        candidates.append((pos, kind, left, right))

    # 1. Sentence / clause ends — strongest boundary.
    for m in re.finditer(r"(?<=[.!?;:])\s+", segment):
        add(m.end(), "punct")

    # 2. Commas — next best.
    for m in re.finditer(r",\s+", segment):
        add(m.end(), "comma")

    # 3. Common conjunctions / clause markers.
    for m in re.finditer(r"\s+(and|but|or|because|so|then|that|while|when|where)\s+",
                         segment, flags=re.IGNORECASE):
        # Split just before the conjunction, preserving it on the new line.
        add(m.start() + 1, "conj")

    # 4. Word boundaries (fallback).
    for m in re.finditer(r"\s+", segment):
        add(m.end(), "word")

    if not candidates:
        return [segment]

    kind_order = {"punct": 0, "comma": 1, "conj": 2, "word": 3}

    def score(c):
        _, kind, left, right = c
        lv = visible_len(left)
        rv = visible_len(right)
        left_over = max(0, lv - max_chars)
        # Prefer candidates where left does NOT overflow.
        # Among overflows, prefer the smallest.
        # Then prefer stronger boundaries and avoid tiny right tails.
        # Finally prefer a longer left part (balanced chunks).
        return (
            0 if lv <= max_chars else 1,           # strict fit first
            left_over,                            # then smallest overflow
            1 if _tiny(right) else 0,              # avoid orphan tails
            kind_order.get(kind, 99),             # natural boundary priority
            -lv,                                  # longer left better
            abs(lv - rv),                         # balance
        )

    # Only consider candidates where the left side isn't absurdly long.
    viable = [c for c in candidates if visible_len(c[2]) <= max_chars + overflow]
    if not viable:
        return [segment]

    viable.sort(key=score)
    _, _, left, right = viable[0]

    return [left] + _split_segment(right, max_chars, overflow)


def capitalize_line(line: str, preserve_continuation: bool = True) -> str:
    """
    Capitalize the first alphabetic character of `line`, unless it is a
    mid-sentence continuation (starts with '...' or a two-speaker hyphen).
    """
    line = line.strip()
    if not line:
        return line

    # Mid-sentence continuation starting with ellipsis
    if preserve_continuation:
        if line.startswith("..."):
            return line
        if line.startswith("-"):
            after = line.lstrip("-").lstrip()
            if after.startswith("..."):
                return line

    # Find first alphabetic character and uppercase it.
    m = re.search(r"[a-zA-Z]", line)
    if m and m.group(0).islower():
        idx = m.start()
        return line[:idx] + line[idx].upper() + line[idx + 1:]
    return line


def normalize_line_breaks(text: str) -> str:
    """Collapse multiple spaces and normalize whitespace around tags."""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    return text.strip()


def sentence_case(text: str, hyphen_continuation: bool = True) -> str:
    """Apply sentence-case capitalization to each line of text."""
    lines = text.split("\n")
    return "\n".join(capitalize_line(ln, hyphen_continuation) for ln in lines)
