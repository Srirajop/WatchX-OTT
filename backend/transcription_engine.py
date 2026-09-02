"""Local transcription helpers with stable-ts timestamp stabilization."""

from __future__ import annotations

import os
import hashlib
import json
from pathlib import Path
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
    cache_dir = Path(os.getenv("WATCHX_CACHE_DIR", Path(__file__).with_name(".cache")))
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        stat = os.stat(audio_path)
        key = hashlib.sha256(f"{audio_path}:{stat.st_size}:{stat.st_mtime_ns}:{model_size}".encode()).hexdigest()
        cache_file = cache_dir / f"transcription-{key}.json"
        if cache_file.exists():
            payload = json.loads(cache_file.read_text(encoding="utf-8"))
            return payload["segments"], payload["engine"] + " (cache)"
    except OSError:
        cache_file = None

    def serialize_segments(segments, engine, language=None):
        output = []
        for segment in segments:
            words = []
            for word in (getattr(segment, "words", None) or []):
                start = getattr(word, "start", None)
                end = getattr(word, "end", None)
                if start is None or end is None:
                    continue
                words.append({"word": getattr(word, "word", "").strip(), "start": float(start),
                              "end": float(end), "confidence": getattr(word, "probability", None)})
            item = {"start": float(segment.start), "end": float(segment.end),
                    "text": segment.text.strip(), "words": words,
                    "confidence": getattr(segment, "avg_logprob", None),
                    "language": language}
            if item["text"]:
                output.append(item)
        if cache_file:
            cache_file.write_text(json.dumps({"segments": output, "engine": engine}), encoding="utf-8")
        return output, engine
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
        return serialize_segments(result.segments, "stable-ts", getattr(result, "language", None))
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
        return serialize_segments(segments_gen, f"Faster-Whisper fallback (stable-ts unavailable: {stable_error})", getattr(_info, "language", None))
