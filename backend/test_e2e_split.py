# -*- coding: utf-8 -*-
"""End-to-end test through prepare_for_platform with Disney FNG settings"""
import sys, os
sys.path.insert(0, '.')
os.environ.setdefault('GROQ_API_KEY', 'dummy')

from timecoded_subtitles import prepare_for_platform

# Disney FNG platform dict (key values)
platform = {
    "name": "Disney FNG",
    "max_chars_per_line": 38,
    "max_lines": 2,
    "min_duration_seconds": 1.0,
    "max_duration_seconds": 7.0,
    "min_interval_seconds": 0.08,
    "reading_speed_max_cps": 21,
    "zero_subtitle_required": False,
}

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

result = prepare_for_platform(subs, platform, "Castle-F006.srt")

print(f"Input:  {len(subs)} cues")
print(f"Output: {len(result)} cues\n")
for s in result:
    lines = s['text'].split('\n')
    duration = 0.0
    try:
        from timecoded_subtitles import _to_seconds
        st = _to_seconds(s['start_time'])
        en = _to_seconds(s['end_time'])
        if st is not None and en is not None:
            duration = en - st
    except:
        pass
    print(f"  [{s['id']:3d}] {s['start_time']} --> {s['end_time']}  ({duration:.2f}s)")
    for ln in lines:
        c = len(ln.replace('<i>', '').replace('</i>', ''))
        flag = " <-- OVER 38!" if c > 38 else ""
        print(f"         ({c:2d}) {ln!r}{flag}")
    print()
