# -*- coding: utf-8 -*-
"""Test cue splitting with exact examples from the screenshot"""
import sys
sys.path.insert(0, '.')

from timecoded_subtitles import _split_long_subtitles

# Subtitle 103 from screenshot: 01:07:33,680 --> 01:07:39,480
# That's 5.8 seconds of long dialogue
subs = [
    {
        "id": 103,
        "start_time": "01:07:33,680",
        "end_time": "01:07:39,480",
        "text": "Listen, Freud. I know what you're trying to do. You're trying to get me to talk about my mom to see if you can squeeze any more pulp for your fiction.",
        "original_text": "",
        "flagged": False,
        "flag_reason": "",
    },
    {
        "id": 104,
        "start_time": "01:07:39,560",
        "end_time": "01:07:46,560",
        "text": '"Pulp"? You think what I do is pulp? Listen, I will have you know that The New York Review of Books, not The New York Times Book Review, mind you.',
        "original_text": "",
        "flagged": False,
        "flag_reason": "",
    },
    # A normal-length subtitle — should pass through unchanged
    {
        "id": 105,
        "start_time": "01:07:47,000",
        "end_time": "01:07:49,000",
        "text": "That's funny.",
        "original_text": "",
        "flagged": False,
        "flag_reason": "",
    },
]

result = _split_long_subtitles(subs, max_chars=38, max_lines=2)

print(f"Input:  {len(subs)} cues")
print(f"Output: {len(result)} cues\n")
for i, s in enumerate(result, 1):
    lines = s['text'].split('\n')
    print(f"  [{i}] {s['start_time']} --> {s['end_time']}")
    for ln in lines:
        char_count = len(ln.replace('<i>', '').replace('</i>', ''))
        flag = " <-- TOO LONG!" if char_count > 38 else ""
        print(f"       ({char_count:2d} chars) {ln!r}{flag}")
    print()
