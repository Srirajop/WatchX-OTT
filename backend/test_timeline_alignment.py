import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from timeline_alignment import align_subtitles_to_client, classify_alignment, transform_time


def test_identical_and_global_offset():
    assert classify_alignment([(0, 0), (100, 100)]) == "IDENTICAL"
    assert classify_alignment([(0, 15), (100, 115)]) == "GLOBAL_OFFSET"
    assert transform_time(42, [(0, 15), (100, 115)]) == 57


def test_fps_transform_and_piecewise_inserted_scene():
    assert classify_alignment([(0, 0), (100, 104)]) == "FPS_TRANSFORM"
    assert classify_alignment([(0, 10), (100, 110), (200, 240)]) == "PIECEWISE"


def test_subtitle_text_and_timing_validation():
    subs = [{"id": 1, "text": "Client exact text", "start_time": "00:00:10,000", "end_time": "00:00:12,000"}]
    result, report = align_subtitles_to_client(subs, [(0, 15), (100, 115)], client_duration=200)
    assert result[0]["text"] == "Client exact text"
    assert result[0]["start_time"] == "00:00:25,000"
    assert result[0]["end_time"] == "00:00:27,000"
    assert report["auto_mapped"] == 1 and report["unresolved"] == 0


def test_invalid_or_contradictory_anchors_fail():
    try:
        align_subtitles_to_client([], [(0, 10), (0, 20)])
    except ValueError:
        return
    raise AssertionError("contradictory anchors should fail")
