# platform_rules.py
# Platform rules are loaded from the database (added via Rules & Guidelines tab).
# The PLATFORMS dict below contains ONLY the internal "generic" fallback used by
# the cleaning and quality-check engine when no specific platform is selected.
# Do NOT add OTT platforms here — use the Rules & Guidelines UI to upload guidelines.

PLATFORMS = {
    # ── Internal fallback only — NOT shown in the platform dropdown ───────────
    "generic": {
        "name": "Generic / Other",
        "max_chars_per_line": 42,
        "max_lines": 2,
        "min_duration_seconds": 1.0,
        "max_duration_seconds": 7.0,
        "min_interval_seconds": 0.02,
        "fps": 25,
        "venue": "Broadcast",
        "two_speaker_format": "hyphen_no_space",
        "zero_subtitle_required": False,
        "file_format": "SRT",
        "rules": [
            "Maximum 42 characters per line",
            "Maximum 2 lines per subtitle",
            "Minimum duration: 1 second",
            "Maximum duration: 7 seconds",
            "Standard punctuation rules apply",
            "Sentence case throughout",
        ],
        "remove_elements": ["stage_directions", "character_names", "scene_descriptions",
                           "slang_notes"],
    },
}


def get_platform(platform_key: str) -> dict:
    """
    Look up a platform's rules.
    Checks the database for custom platforms added via /platforms/add.
    Falls back to 'generic' if the platform key is not found anywhere.
    """
    if platform_key in PLATFORMS:
        return PLATFORMS[platform_key]

    try:
        from database import get_all_platforms
        db_platforms = get_all_platforms()
        if platform_key in db_platforms:
            return db_platforms[platform_key]
    except Exception as e:
        print(f"[platform_rules] Could not load platform '{platform_key}' from DB: {e}")

    return PLATFORMS["generic"]


def get_platform_list() -> list:
    """Return a minimal static list (only generic). UI should prefer the /platforms endpoint."""
    return [
        {"key": "generic", "name": "Generic / Other", "max_chars": 42,
         "max_lines": 2, "file_format": "SRT", "is_custom": False}
    ]


def get_profanity_table(platform_key: str) -> dict:
    p = get_platform(platform_key)
    return p.get("profanity_table", {})


# Universal SDI House Protocol timing guidelines used by the QC engine.
# These are NOT OTT-platform-specific — they apply universally to frame-gap checks.
UNIVERSAL_GUIDELINES = {
    "frame_header": 3,
    "frame_tail": 5,
    "frame_tail_reading_speed_max": 12,
    "min_gap_frames": 2,
    "forbidden_gap_range": (3, 11),  # gaps of 3-11 frames not allowed
    "shot_change_cue_in_window": 12,
    "shot_change_cue_out_window": 12,
    "crossing_shot_change": {
        "start_before_1_7_frames": "move_to_first_frame_after_shot_change",
        "start_before_8_11_frames": "move_to_12_frames_before_shot_change",
        "end_after_1_7_frames": "move_to_2_frames_before_shot_change",
        "end_after_8_11_frames": "keep_12_frames_after_shot_change",
    },
    "rules": [
        "3 frame header, 5 frame tail (add up to 12 frame tail for reading speed)",
        "No gaps of 3-11 frames between subtitles — must be 2 frames or 12+ frames",
        "Close gaps by extending out-time of previous subtitle",
        "If speech starts on/within 12 frames after shot change — cue in at shot change",
        "If out-time within 12 frames before shot change — extend to shot change",
    ]
}
