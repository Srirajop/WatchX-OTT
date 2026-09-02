import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from transcript_aligner import align_transcription_to_script
from timeline_alignment import transform_time


def cue(text, start, end, words=None):
    item = {"id": 1, "text": text, "start_time": start, "end_time": end}
    if words:
        item["words"] = words
    return item


def test_client_wording_is_preserved_and_stable_word_times_are_used():
    whisper = [cue("I can't go", "00:00:01,000", "00:00:03,000", [
        {"word": "I", "start": 1.0, "end": 1.2, "probability": .9},
        {"word": "cannot", "start": 1.2, "end": 1.8, "probability": .8},
        {"word": "go", "start": 1.8, "end": 2.2, "probability": .9},
    ])]
    result = align_transcription_to_script(whisper, [{"text": "I cannot go"}])
    assert result[0]["text"] == "I cannot go"
    assert result[0]["start_time"] == "00:00:01,000"
    assert result[0]["end_time"] == "00:00:02,200"
    assert not result[0]["manual_placement"]


def test_unmatched_dialogue_has_no_fabricated_timestamp():
    result = align_transcription_to_script(
        [cue("hello there", "00:00:01,000", "00:00:02,000")],
        [{"text": "A completely unrelated sentence"}],
    )
    assert result[0]["start_time"] == ""
    assert result[0]["end_time"] == ""
    assert result[0]["flagged"]
    assert result[0]["manual_placement"] is False


def test_piecewise_timeline_mapping_handles_multiple_offsets():
    anchors = [(0, 80), (600, 680), (1800, 1935)]
    assert transform_time(300, anchors) == 380
    assert abs(transform_time(1200, anchors) - 1307.5) < 1e-9


def test_global_mapping_handles_splits_merges_repeats_short_lines_and_gaps():
    whisper = [
        cue("Yeah, come on", "00:00:01,000", "00:00:03,000"),
        cue("I saw the color", "00:00:10,000", "00:00:12,000"),
        cue("No", "00:01:00,000", "00:01:01,000"),
        cue("No", "00:01:05,000", "00:01:06,000"),
    ]
    result = align_transcription_to_script(whisper, [
        {"text": "Yeah"}, {"text": "Come on"}, {"text": "I saw the colour"},
        {"text": "missing dialogue"}, {"text": "No"}, {"text": "No"},
    ])
    assert result[0]["status"] == "AUTO_MAPPED"
    assert result[1]["status"] == "AUTO_MAPPED"
    assert result[2]["status"] == "AUTO_MAPPED"
    assert result[2]["start_time"] == "00:00:10,000"
    assert result[3]["status"] == "UNMATCHED"
    assert result[3]["start_time"] == ""
    assert result[4]["status"] == "AUTO_MAPPED"
    assert result[5]["status"] == "AUTO_MAPPED"


def test_several_unmatched_lines_do_not_consume_following_anchor():
    result = align_transcription_to_script(
        [cue("first", "00:00:01,000", "00:00:02,000"), cue("last", "00:01:00,000", "00:01:01,000")],
        [{"text": "first"}, {"text": "unknown one"}, {"text": "unknown two"}, {"text": "last"}],
    )
    assert result[0]["status"] == "AUTO_MAPPED"
    assert result[1]["status"] == result[2]["status"] == "UNMATCHED"
    assert result[3]["status"] == "AUTO_MAPPED"
    assert result[3]["start_time"] == "00:01:00,000"
