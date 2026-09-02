"""Focused regression coverage for the production script/timeline mapper.

These tests use small synthetic Whisper payloads so they do not download or
load the embedding model. The cross-language case injects a deterministic
similarity matrix, which tests the mapper's multilingual integration without
making a network call.
"""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))

from transcript_aligner import align_transcription_to_script
from bridge_translator import build_bridge_texts


def cue(text, start, end, words=None):
    item = {"text": text, "start_time": start, "end_time": end}
    if words is not None:
        item["words"] = words
    return item


def wordcue(text, start, end, words):
    return cue(text, start, end, [
        {"word": word, "start": ws, "end": we, "probability": 0.95}
        for word, ws, we in words
    ])


def map_without_semantics(whisper, client):
    with patch("semantic_matcher.multilingual_scores", return_value=None):
        return align_transcription_to_script(whisper, client)


def test_exact_match():
    result = map_without_semantics([cue("Hello there", "00:00:01,000", "00:00:02,000")], [{"text": "Hello there"}])
    assert result[0]["status"] == "AUTO_MAPPED"
    assert result[0]["start_time"] == "00:00:01,000"


def test_punctuation_difference():
    result = map_without_semantics([cue("Hello, there!", "00:00:01,000", "00:00:02,000")], [{"text": "Hello there"}])
    assert result[0]["status"] == "AUTO_MAPPED"


def test_contraction_difference():
    result = map_without_semantics([cue("I can't go", "00:00:01,000", "00:00:02,000")], [{"text": "I cannot go"}])
    assert result[0]["status"] == "AUTO_MAPPED"


def test_spelling_error():
    result = map_without_semantics([cue("The color is red", "00:00:01,000", "00:00:02,000")], [{"text": "The colour is red"}])
    assert result[0]["status"] == "AUTO_MAPPED"


def test_whisper_split_client_merged_uses_real_span():
    whisper = [
        wordcue("I saw the color", "00:00:01,000", "00:00:04,000", [
            ("I", 1.0, 1.2), ("saw", 1.3, 1.6), ("the", 1.7, 1.9), ("color", 2.0, 2.4),
        ]),
        wordcue("yesterday", "00:00:04,500", "00:00:05,500", [("yesterday", 4.5, 5.1)]),
    ]
    result = map_without_semantics(whisper, [{"text": "I saw the colour yesterday"}])
    assert result[0]["status"] == "AUTO_MAPPED"
    assert result[0]["matched_whisper_indices"] == [0, 1]
    assert result[0]["start_time"] == "00:00:01,000"
    assert result[0]["end_time"] == "00:00:05,080"


def test_whisper_merged_client_split_uses_word_boundaries():
    whisper = [wordcue("Yeah, come on", "00:00:01,000", "00:00:03,000", [
        ("Yeah", 1.0, 1.3), ("come", 1.5, 1.8), ("on", 1.8, 2.0),
    ])]
    result = map_without_semantics(whisper, [{"text": "Yeah"}, {"text": "Come on"}])
    assert [x["status"] for x in result] == ["AUTO_MAPPED", "AUTO_MAPPED"]
    assert result[0]["end_time"] == "00:00:01,280"
    assert result[1]["start_time"] == "00:00:01,520"


def test_repeated_dialogue_is_resolved_in_order():
    whisper = [cue("No", "00:00:01,000", "00:00:01,400"), cue("No", "00:00:09,000", "00:00:09,400")]
    result = map_without_semantics(whisper, [{"text": "No"}, {"text": "No"}])
    assert [x["start_time"] for x in result] == ["00:00:01,000", "00:00:09,000"]


def test_short_dialogue_is_not_lost():
    result = map_without_semantics([cue("Yeah, I know", "00:00:01,000", "00:00:03,000")], [{"text": "Yeah"}])
    assert result[0]["status"] == "AUTO_MAPPED"


def test_one_unmatched_line_does_not_consume_following_anchor():
    result = map_without_semantics(
        [cue("first", "00:00:01,000", "00:00:02,000"), cue("last", "00:01:00,000", "00:01:01,000")],
        [{"text": "first"}, {"text": "not spoken"}, {"text": "last"}],
    )
    assert result[1]["status"] == "UNMATCHED"
    assert result[2]["start_time"] == "00:01:00,000"


def test_consecutive_unmatched_lines_remain_untimed():
    result = map_without_semantics(
        [cue("first", "00:00:01,000", "00:00:02,000"), cue("last", "00:01:00,000", "00:01:01,000")],
        [{"text": "first"}, {"text": "unknown one"}, {"text": "unknown two"}, {"text": "last"}],
    )
    assert all(result[i]["status"] == "UNMATCHED" and not result[i]["start_time"] for i in (1, 2))
    assert result[3]["status"] == "AUTO_MAPPED"


def test_long_silence_does_not_change_reference_timing():
    result = map_without_semantics(
        [cue("before", "00:00:01,000", "00:00:02,000"), cue("after", "00:10:00,000", "00:10:01,000")],
        [{"text": "before"}, {"text": "after"}],
    )
    assert result[1]["start_time"] == "00:10:00,000"


def test_neighboring_context_disambiguates_repeated_short_line():
    whisper = [
        cue("Open the door", "00:00:01,000", "00:00:02,000"),
        cue("Yeah", "00:00:02,500", "00:00:02,800"),
        cue("Close the window", "00:00:05,000", "00:00:06,000"),
        cue("Yeah", "00:00:06,500", "00:00:06,800"),
    ]
    result = map_without_semantics(whisper, [
        {"text": "Open the door"}, {"text": "Yeah"}, {"text": "Close the window"}, {"text": "Yeah"},
    ])
    assert [x["start_time"] for x in result] == [
        "00:00:01,000", "00:00:02,480", "00:00:05,000", "00:00:06,480"
    ]


def test_cross_language_semantic_candidate_preserves_client_text():
    whisper = [cue("Hello, how are you?", "00:00:01,000", "00:00:03,000")]
    client = [{"text": "Hola, ¿cómo estás?"}]
    with patch("semantic_matcher.model_status", return_value={"cached": True}), \
         patch("semantic_matcher.multilingual_scores", return_value=__import__("numpy").array([[0.91]])):
        result = align_transcription_to_script(whisper, client)
    assert result[0]["text"] == client[0]["text"]
    assert result[0]["status"] == "AUTO_MAPPED"
    assert result[0]["start_time"] == "00:00:01,000"


def test_local_bridge_translates_each_cue_without_changing_client_indices():
    with patch("bridge_translator._detect", side_effect=["aa", "bb"]), \
         patch("bridge_translator._argos_translation", return_value=object()), \
         patch("bridge_translator._translate_argos", side_effect=lambda _translator, text: {"client one": "spoken one", "client two": "spoken two"}[text]):
        result = build_bridge_texts(
            [{"text": "spoken one"}, {"text": "spoken two"}],
            [{"text": "client one"}, {"text": "client two"}],
        )
    assert result.used is True
    assert result.texts == ["spoken one", "spoken two"]
    assert result.source_language == "aa" and result.target_language == "bb"
