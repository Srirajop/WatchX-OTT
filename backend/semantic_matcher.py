"""Lazy multilingual semantic matching for subtitle alignment.

The model is intentionally local and small; it is never used to generate or
translate subtitle text.  If unavailable, callers retain deterministic lexical
alignment behavior.
"""
import os
import numpy as np
from pathlib import Path

_MODEL = None
_FAILED = False
MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

def model_status():
    name = os.getenv("WATCHX_EMBEDDING_MODEL", MODEL_NAME)
    cache = Path(os.getenv("WATCHX_MODEL_CACHE", Path(__file__).with_name(".models")))
    model_root = cache / "models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2"
    snapshots = sorted((model_root / "snapshots").glob("*")) if (model_root / "snapshots").exists() else []
    snapshot = next((p for p in snapshots if p.is_dir()), None)
    # A weight file alone is not a usable Sentence-Transformers model. Require
    # the local module/config/tokenizer metadata too, otherwise the library
    # silently tries Hugging Face network retries during alignment.
    required_names = (
        "modules.json", "config.json", "config_sentence_transformers.json",
        "sentence_bert_config.json", "model.safetensors", "tokenizer.json",
        "tokenizer_config.json", "special_tokens_map.json", "1_Pooling/config.json",
    )
    valid_files = bool(snapshot) and all(
        (snapshot / name).is_file() and (snapshot / name).stat().st_size > 0
        for name in required_names
    )
    return {"model": name, "cached": (cache / "semantic-model.ready").exists() and valid_files,
            "loaded": _MODEL is not None, "cache_dir": str(cache),
            "snapshot_dir": str(snapshot) if snapshot else ""}

def prepare_model():
    global _MODEL, _FAILED
    from sentence_transformers import SentenceTransformer
    status = model_status(); cache = Path(status["cache_dir"]); cache.mkdir(parents=True, exist_ok=True)
    print(f"[semantic-model] loading {status['model']} from {cache}", flush=True)
    model_ref = status.get("snapshot_dir") if status.get("cached") else status["model"]
    _MODEL = SentenceTransformer(
        model_ref,
        device="cpu",
        cache_folder=str(cache),
        local_files_only=bool(status.get("cached")),
    )
    (cache / "semantic-model.ready").write_text(status["model"], encoding="utf-8")
    _FAILED = False
    print("[semantic-model] ready in memory", flush=True)
    return model_status()


def multilingual_scores(source_texts, target_texts):
    global _MODEL, _FAILED
    if _FAILED or not source_texts or not target_texts:
        return None
    try:
        from sentence_transformers import SentenceTransformer
        if _MODEL is None:
            status = model_status()
            if not status["cached"]:
                raise RuntimeError("Multilingual model is not prepared. Use the setup action first.")
            if os.getenv("WATCHX_ALLOW_RUNTIME_MODEL_LOAD", "0").lower() not in ("1", "true", "yes"):
                raise RuntimeError("Multilingual model is cached but not loaded in this server process. Run the setup action in this server process.")
            _MODEL = SentenceTransformer(
                status.get("snapshot_dir") or status["model"],
                device="cpu",
                cache_folder=status["cache_dir"],
                local_files_only=True,
            )
        a = _MODEL.encode(source_texts, normalize_embeddings=True, show_progress_bar=False)
        b = _MODEL.encode(target_texts, normalize_embeddings=True, show_progress_bar=False)
        return np.matmul(np.asarray(a), np.asarray(b).T)
    except Exception as exc:
        _FAILED = True
        print(f"[semantic-align] local multilingual model unavailable: {exc}")
        return None
