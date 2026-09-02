"""Local, cue-preserving translation bridge for cross-language alignment.

The bridge is never exported and never replaces client dialogue. It translates
each cue independently into the detected spoken language so the existing
Whisper/Stable-ts word timeline can be aligned with same-language text.

Argos packages are intentionally read from the local installation only during
alignment. Package download/installation belongs to an explicit setup action;
alignment must not unexpectedly access the network.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import queue
import threading


BRIDGE_TRANSLATION_TIMEOUT_SECONDS = float(
    os.getenv("WATCHX_BRIDGE_TIMEOUT_SECONDS", "20")
)


class BridgeUnavailable(RuntimeError):
    """Raised when a local language bridge is not installed for this pair."""


def _detect(texts: list[str]) -> str:
    try:
        from langdetect import DetectorFactory, detect_langs
        DetectorFactory.seed = 0
    except Exception as exc:
        raise BridgeUnavailable(
            "Language detection is unavailable. Install the lightweight "
            "langdetect dependency during WatchX setup."
        ) from exc
    sample = " ".join((text or "").strip() for text in texts if len((text or "").strip()) >= 12)
    if not sample:
        sample = " ".join((text or "").strip() for text in texts)
    if not sample.strip():
        raise BridgeUnavailable("Could not detect a language from empty subtitle text.")
    # Language detectors are unreliable on a single short interjection. It is
    # safer to use the semantic fallback than to translate an English cue into
    # the wrong bridge language.
    if len(sample) < 40:
        raise BridgeUnavailable("Not enough text for a reliable language bridge decision.")
    try:
        ranked = detect_langs(sample)
        if not ranked or float(ranked[0].prob) < 0.80:
            raise BridgeUnavailable("Language detection was too uncertain for a safe bridge.")
        return ranked[0].lang
    except Exception as exc:
        raise BridgeUnavailable("Could not detect the subtitle language reliably.") from exc


def _normalise_code(value: str | None) -> str:
    value = (value or "").strip().lower().replace("_", "-")
    return value.split("-", 1)[0]


def _spoken_language(whisper_subs: list[dict]) -> str:
    declared = [str(x.get("language", "")) for x in whisper_subs if x.get("language")]
    if declared:
        return _normalise_code(declared[0])
    return _detect([x.get("text", "") for x in whisper_subs])


def detect_languages(whisper_subs: list[dict], client_subs: list[dict]) -> tuple[str, str]:
    """Return (client_language, spoken_language) without downloading anything."""
    return _detect([x.get("text", "") for x in client_subs]), _spoken_language(whisper_subs)


def _argos_translation(source_code: str, target_code: str):
    try:
        from argostranslate import translate
        installed = translate.get_installed_languages()
    except Exception as exc:
        raise BridgeUnavailable(
            "The local Argos Translate bridge is not installed. Run WatchX setup "
            "to enable cross-language alignment."
        ) from exc
    source = next((x for x in installed if x.code == source_code), None)
    target = next((x for x in installed if x.code == target_code), None)
    if source is None or target is None:
        raise BridgeUnavailable(
            f"No local translation package is installed for {source_code} -> {target_code}. "
            "Prepare this language pair in WatchX setup."
        )
    try:
        return source.get_translation(target)
    except Exception as exc:
        raise BridgeUnavailable(
            f"No local Argos translation path is installed for {source_code} -> {target_code}."
        ) from exc


def _translate_argos(translator, text: str) -> str:
    """Translate without Argos' optional sentence-boundary downloader.

    The normal high-level Argos call may initialize an external sentence
    boundary component. Cue text is already segmented by the client subtitle,
    so direct package tokenization is both faster and deterministic here.
    """
    underlying = getattr(translator, "underlying", translator)
    pkg = underlying.pkg
    if getattr(underlying, "translator", None) is None:
        import ctranslate2
        underlying.translator = ctranslate2.Translator(
            str(pkg.package_path / "model"), device="cpu", inter_threads=1, intra_threads=1
        )
    tokens = pkg.tokenizer.encode(text)
    kwargs = {
        "replace_unknowns": True,
        "beam_size": 1,
        "num_hypotheses": 1,
        "return_scores": True,
    }
    if getattr(pkg, "target_prefix", ""):
        kwargs["target_prefix"] = [[pkg.target_prefix]]
    batch = underlying.translator.translate_batch([tokens], **kwargs)[0]
    value = pkg.tokenizer.decode(batch.hypotheses[0])
    if getattr(pkg, "target_prefix", "") and value.startswith(pkg.target_prefix):
        value = value[len(pkg.target_prefix):]
    return value.lstrip()


@dataclass(frozen=True)
class BridgeResult:
    texts: list[str]
    source_language: str
    target_language: str
    used: bool


def build_bridge_texts(whisper_subs: list[dict], client_subs: list[dict], progress_callback=None) -> BridgeResult:
    """Translate client cues one-by-one into the spoken language, if needed."""
    client_texts = [str(x.get("text", "")) for x in client_subs]
    source = _detect(client_texts)
    target = _spoken_language(whisper_subs)
    if source == target:
        return BridgeResult(client_texts, source, target, False)
    translator = _argos_translation(source, target)
    translated = []
    total = len(client_texts)
    for cue_index, text in enumerate(client_texts):
        if not text.strip():
            translated.append("")
            if progress_callback:
                try:
                    progress_callback(cue_index + 1, total)
                except Exception:
                    pass
            continue
        result_queue = queue.Queue(maxsize=1)

        def _translate():
            try:
                result_queue.put((True, _translate_argos(translator, text)))
            except Exception as exc:
                result_queue.put((False, exc))

        # A corrupt/incompatible local pack must not hold the alignment worker
        # forever. The daemon thread is deliberately abandoned on timeout;
        # alignment can continue through the existing verified fallback path.
        worker = threading.Thread(target=_translate, daemon=True)
        worker.start()
        worker.join(timeout=BRIDGE_TRANSLATION_TIMEOUT_SECONDS)
        if worker.is_alive():
            raise BridgeUnavailable(
                "The local language bridge timed out while translating a cue "
                f"after {int(BRIDGE_TRANSLATION_TIMEOUT_SECONDS)} seconds."
            )
        try:
            ok, value = result_queue.get_nowait()
        except queue.Empty as exc:
            raise BridgeUnavailable("The local language bridge returned no result.") from exc
        if not ok:
            raise BridgeUnavailable(f"The local language bridge failed: {value}") from value
        value = (value or "").strip()
        if not value:
            raise BridgeUnavailable(f"The local bridge returned no text for client cue {len(translated) + 1}.")
        translated.append(value)
        if progress_callback:
            try:
                progress_callback(cue_index + 1, total)
            except Exception:
                pass
    return BridgeResult(translated, source, target, True)


def status() -> dict:
    """Return setup information without downloading anything."""
    try:
        from argostranslate import translate
        installed = translate.get_installed_languages()
        codes = sorted({x.code for x in installed})
        return {"available": True, "ready": bool(codes), "installed_languages": codes,
                "message": "Local bridge available." if codes else "Argos is installed; language packs still need setup."}
    except Exception:
        return {
            "available": False,
            "ready": False,
            "installed_languages": [],
            "message": "Install Argos Translate and the required language packages during setup.",
        }


def prepare_language_pair(source_language: str, target_language: str) -> dict:
    """Download/install one Argos pair from an explicit setup action."""
    source_code = _normalise_code(source_language)
    target_code = _normalise_code(target_language)
    if not source_code or not target_code or source_code == target_code:
        return status() | {"prepared_pair": f"{source_code}->{target_code}"}
    try:
        from argostranslate import translate
        import argostranslate.package as package
        installed = translate.get_installed_languages()
        source = next((x for x in installed if x.code == source_code), None)
        target = next((x for x in installed if x.code == target_code), None)
        if source is not None and target is not None and source.get_translation(target) is not None:
            return status() | {"prepared_pair": f"{source_code}->{target_code}"}
        package.update_package_index()
        candidates = [
            p for p in package.get_available_packages()
            if p.from_code == source_code and p.to_code == target_code
        ]
        if not candidates:
            raise BridgeUnavailable(
                f"No Argos package is available for {source_code} -> {target_code}. "
                "Install a supported package or use a same-language reference."
            )
        path = candidates[0].download()
        package.install_from_path(path)
        return status() | {"prepared_pair": f"{source_code}->{target_code}"}
    except BridgeUnavailable:
        raise
    except Exception as exc:
        raise BridgeUnavailable(f"Could not prepare the local {source_code} -> {target_code} bridge: {exc}") from exc
