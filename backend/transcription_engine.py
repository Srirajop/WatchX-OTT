"""Local transcription helpers with stable-ts timestamp stabilization."""

from __future__ import annotations

import os
from typing import Callable


def transcribe_with_stable_timestamps(
    audio_path: str,
    progress_callback: Callable[[float, float], None] | None = None,
    model_size: str | None = None,
) -> tuple[list[dict], str]:
    """Transcribe using stable-ts over Faster-Whisper.

    stable-ts keeps Faster-Whisper's recognition speed while refining the
    word/segment boundaries around speech and silence.  The returned cues are
    deliberately plain dictionaries so both the standard Transcribe and
    Transcribe + Align routes share exactly the same timing source.

    ``base`` is the safe CPU default: stable timestamp post-processing uses
    materially more memory than plain Faster-Whisper, and ``small`` can fail
    with an MKL allocation error on typical workstation RAM.  Set
    ``STABLE_TS_MODEL`` to ``small`` or another supported Whisper model only
    on a machine with sufficient memory.
    """
    model_size = model_size or os.getenv("STABLE_TS_MODEL", "base")
    try:
        os.environ["OMP_NUM_THREADS"] = "2"
        os.environ["MKL_NUM_THREADS"] = "2"
        import stable_whisper

        model = stable_whisper.load_faster_whisper(
            model_size, device="cpu", compute_type="int8", cpu_threads=2, num_workers=1
        )
        result = model.transcribe(
            audio_path,
            beam_size=5,
            word_timestamps=True,
            # Stable-ts uses these timestamps to regroup speech naturally and
            # prevent cue boundaries from sitting in silent audio.
            regroup=True,
            suppress_silence=True,
            suppress_word_ts=True,
            vad=False,
            verbose=None,
            progress_callback=progress_callback,
        )
        segments = [
            {"start": float(segment.start), "end": float(segment.end), "text": segment.text.strip()}
            for segment in result.segments
            if segment.text and segment.text.strip()
        ]
        return segments, "stable-ts"
    except Exception as stable_error:
        # Keep transcription available on systems where stable-ts cannot load
        # its model/runtime.  The status returned to the caller makes this
        # fallback visible rather than silently claiming stabilized timings.
        from faster_whisper import WhisperModel

        model = WhisperModel(model_size, device="cpu", compute_type="int8", cpu_threads=2, num_workers=1)
        segments_gen, _info = model.transcribe(
            audio_path,
            beam_size=5,
            word_timestamps=True,
            vad_filter=True,
        )
        segments = [
            {"start": float(segment.start), "end": float(segment.end), "text": segment.text.strip()}
            for segment in segments_gen
            if segment.text and segment.text.strip()
        ]
        return segments, f"Faster-Whisper fallback (stable-ts unavailable: {stable_error})"
