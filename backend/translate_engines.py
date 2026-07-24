# translate_engines.py — Multi-provider subtitle translation engine.
#
# Mirrors Subtitle Edit's auto-translate engine list: a subtitler picks a
# provider, pastes their API key (+ optional model / custom endpoint), and
# every subtitle line is translated into the target language.
#
# Supported providers (all driven through ONE unified interface):
#   google            – free, key-less Google Translate web endpoint (default)
#   openai            – ChatGPT / OpenAI (chat/completions)
#   anthropic         – Claude (Anthropic Messages API)
#   gemini            – Google Gemini (Generative Language API)
#   deepl             – DeepL (free & pro)
#   deepseek          – DeepSeek
#   groq              – Groq
#   mistral           – Mistral AI
#   openrouter        – OpenRouter
#   perplexity        – Perplexity
#   openai-compatible – any OpenAI-compatible /v1/chat/completions endpoint
#   ollama            – Ollama (local, OpenAI-compatible)
#   libretranslate    – LibreTranslate (local / hosted)
#   microsoft         – Azure AI Translator
#
# Timecodes / inline <i> <b> tags are preserved because we send each line's
# raw text and ask the model to keep the same number of lines.

import os
import json
import time

import httpx

# ─── DEFAULT PROMPT (used by every AI/chat provider) ──────────────
DEFAULT_PROMPT = (
    "You are a professional subtitler. Translate the following subtitle text "
    "from {source} to {target}. Preserve the original meaning, tone and style. "
    "Keep the exact same number of lines and line breaks. Do NOT add any notes, "
    "headings, quotation marks or explanations — only output the translated "
    "subtitle text."
)

# ─── LANGUAGE CODE MAPS ───────────────────────────────────────────
# Used by the key-less Google endpoint and DeepL (which require language codes).
_GOOGLE_LANG = {
    "english": "en", "spanish": "es", "french": "fr", "german": "de", "italian": "it",
    "portuguese": "pt", "russian": "ru", "arabic": "ar", "hindi": "hi",
    "chinese (simplified)": "zh-CN", "chinese (traditional)": "zh-TW",
    "japanese": "ja", "korean": "ko", "turkish": "tr", "dutch": "nl",
    "polish": "pl", "ukrainian": "uk", "persian": "fa", "greek": "el",
    "hebrew": "he", "thai": "th", "vietnamese": "vi", "indonesian": "id",
    "malay": "ms", "romanian": "ro", "hungarian": "hu", "czech": "cs",
    "swedish": "sv", "danish": "da", "finnish": "fi", "norwegian": "no",
    "catalan": "ca", "bulgarian": "bg", "croatian": "hr", "serbian": "sr",
    "slovak": "sk", "slovenian": "sl", "lithuanian": "lt", "latvian": "lv",
    "estonian": "et", "icelandic": "is", "filipino": "fil", "tamil": "ta",
    "telugu": "te", "urdu": "ur", "bengali": "bn", "thai": "th",
    "norwegian bokmål": "nb", "norwegian nynorsk": "nn",
}

_DEEPL_LANG = {
    "english": "EN", "spanish": "ES", "french": "FR", "german": "DE", "italian": "IT",
    "portuguese": "PT", "russian": "RU", "arabic": "AR", "bulgarian": "BG",
    "czech": "CS", "danish": "DA", "dutch": "NL", "estonian": "ET", "finnish": "FI",
    "greek": "EL", "hungarian": "HU", "indonesian": "ID", "japanese": "JA",
    "korean": "KO", "latvian": "LV", "lithuanian": "LT", "norwegian": "NB",
    "polish": "PL", "romanian": "RO", "slovak": "SK", "slovenian": "SL",
    "swedish": "SV", "turkish": "TR", "ukrainian": "UK", "chinese (simplified)": "ZH",
    "chinese (traditional)": "ZH", "hebrew": "HE", "hindi": "HI",
    "thai": "TH", "vietnamese": "VI",
}


def _code(name: str, table: dict) -> str:
    key = (name or "").strip().lower()
    # Allow callers to pass a code directly (e.g. "en", "EN", "zh-CN")
    if key in table.values():
        return name.strip()
    return table.get(key, key)


# ─── PROVIDER REGISTRY ────────────────────────────────────────────
# `kind` selects the network implementation. `needs_key` flags whether the UI
# should ask the subtitler for an API key. `custom_endpoint` lets the user
# override the base URL (used for local LLMs / self-hosted gateways).
PROVIDERS = {
    "google": {
        "name": "Google Translate (free, no key)",
        "kind": "google",
        "needs_key": False,
        "custom_endpoint": False,
        "models": [],
        "default_model": "",
        "default_base_url": "",
        "env_key": "",
        "note": "No API key required — uses Google's free web endpoint.",
    },
    "openai": {
        "name": "ChatGPT / OpenAI",
        "kind": "openai_compatible",
        "needs_key": True,
        "custom_endpoint": False,
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "gpt-5",
                   "gpt-5-mini", "gpt-5-nano", "gpt-3.5-turbo"],
        "default_model": "gpt-4o-mini",
        "default_base_url": "https://api.openai.com/v1",
        "env_key": "OPENAI_API_KEY",
        "note": "Paste an OpenAI API key from platform.openai.com.",
    },
    "anthropic": {
        "name": "Claude (Anthropic)",
        "kind": "anthropic",
        "needs_key": True,
        "custom_endpoint": False,
        "models": ["claude-3-5-haiku-latest", "claude-3-5-sonnet-latest",
                   "claude-3-7-sonnet-latest", "claude-sonnet-4-0", "claude-opus-4-0"],
        "default_model": "claude-3-5-haiku-latest",
        "default_base_url": "https://api.anthropic.com/v1",
        "env_key": "ANTHROPIC_API_KEY",
        "note": "Paste an Anthropic API key from console.anthropic.com.",
    },
    "gemini": {
        "name": "Google Gemini",
        "kind": "gemini",
        "needs_key": True,
        "custom_endpoint": False,
        "models": ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-pro",
                   "gemini-1.5-flash", "gemini-1.5-pro"],
        "default_model": "gemini-2.0-flash",
        "default_base_url": "",
        "env_key": "GEMINI_API_KEY",
        "note": "Paste a Gemini API key from aistudio.google.com.",
    },
    "deepl": {
        "name": "DeepL",
        "kind": "deepl",
        "needs_key": True,
        "custom_endpoint": True,
        "models": [],
        "default_model": "",
        "default_base_url": "https://api-free.deepl.com/v2",
        "env_key": "DEEPL_API_KEY",
        "note": "DeepL Free uses api-free.deepl.com. DeepL Pro users: set the "
                "endpoint to https://api.deepl.com/v2",
    },
    "deepseek": {
        "name": "DeepSeek",
        "kind": "openai_compatible",
        "needs_key": True,
        "custom_endpoint": False,
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "default_model": "deepseek-chat",
        "default_base_url": "https://api.deepseek.com/v1",
        "env_key": "DEEPSEEK_API_KEY",
        "note": "Paste a DeepSeek API key from platform.deepseek.com.",
    },
    "groq": {
        "name": "Groq",
        "kind": "openai_compatible",
        "needs_key": True,
        "custom_endpoint": False,
        "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant",
                   "llama-4-scout-17b-16e-instruct", "gemma2-9b-it"],
        "default_model": "llama-3.3-70b-versatile",
        "default_base_url": "https://api.groq.com/openai/v1",
        "env_key": "GROQ_API_KEY",
        "note": "Paste a Groq API key from console.groq.com.",
    },
    "mistral": {
        "name": "Mistral AI",
        "kind": "openai_compatible",
        "needs_key": True,
        "custom_endpoint": False,
        "models": ["mistral-small-latest", "mistral-large-latest", "open-mistral-7b"],
        "default_model": "mistral-small-latest",
        "default_base_url": "https://api.mistral.ai/v1",
        "env_key": "MISTRAL_API_KEY",
        "note": "Paste a Mistral API key from console.mistral.ai.",
    },
    "openrouter": {
        "name": "OpenRouter",
        "kind": "openai_compatible",
        "needs_key": True,
        "custom_endpoint": False,
        "models": ["openai/gpt-4o-mini", "anthropic/claude-3.5-haiku",
                   "google/gemini-2.0-flash-exp", "meta-llama/llama-3.3-70b-instruct",
                   "deepseek/deepseek-chat-v3-0324"],
        "default_model": "openai/gpt-4o-mini",
        "default_base_url": "https://openrouter.ai/api/v1",
        "env_key": "OPENROUTER_API_KEY",
        "note": "Paste an OpenRouter API key from openrouter.ai/keys.",
    },
    "perplexity": {
        "name": "Perplexity",
        "kind": "openai_compatible",
        "needs_key": True,
        "custom_endpoint": False,
        "models": ["sonar", "sonar-pro", "llama-3.1-sonar-large-32k-online"],
        "default_model": "sonar",
        "default_base_url": "https://api.perplexity.ai",
        "env_key": "PERPLEXITY_API_KEY",
        "note": "Paste a Perplexity API key from perplexity.ai/settings/api.",
    },
    "openai-compatible": {
        "name": "OpenAI-Compatible API (custom)",
        "kind": "openai_compatible",
        "needs_key": False,
        "custom_endpoint": True,
        "models": [],
        "default_model": "",
        "default_base_url": "",
        "env_key": "",
        "note": "Point at any OpenAI-compatible /v1/chat/completions endpoint "
                "(vLLM, LM Studio, Together, xAI, etc.). Fill the endpoint + model.",
    },
    "ollama": {
        "name": "Ollama (local)",
        "kind": "openai_compatible",
        "needs_key": False,
        "custom_endpoint": True,
        "models": ["llama3", "llama3.1", "mistral", "gemma2", "qwen2.5"],
        "default_model": "llama3",
        "default_base_url": "http://localhost:11434/v1",
        "env_key": "",
        "note": "Runs locally via Ollama. No API key needed. Start Ollama and "
                "pull a model (e.g. `ollama pull llama3`).",
    },
    "libretranslate": {
        "name": "LibreTranslate (local / hosted)",
        "kind": "libretranslate",
        "needs_key": False,
        "custom_endpoint": True,
        "models": [],
        "default_model": "",
        "default_base_url": "http://localhost:5000",
        "env_key": "LIBRETRANSLATE_API_KEY",
        "note": "Open-source translator. No key for default installs; some "
                "hosts require one. Needs language codes (e.g. en, es).",
    },
    "microsoft": {
        "name": "Microsoft Azure Translator",
        "kind": "microsoft",
        "needs_key": True,
        "custom_endpoint": True,
        "models": [],
        "default_model": "",
        "default_base_url": "",
        "env_key": "AZURE_TRANSLATOR_KEY",
        "note": "Paste your Azure Translator key. Set the endpoint field to your "
                "region (e.g. eastus). Needs language codes (e.g. en, es).",
    },
}


def get_provider_list() -> list:
    """Return JSON-serializable provider metadata for the frontend dropdown."""
    out = []
    for key, meta in PROVIDERS.items():
        out.append({
            "value": key,
            "name": meta["name"],
            "needs_key": meta["needs_key"],
            "custom_endpoint": meta["custom_endpoint"],
            "models": meta["models"],
            "default_model": meta["default_model"],
            "default_base_url": meta["default_base_url"],
            "note": meta["note"],
        })
    return out


def normalize_provider(provider: str) -> str:
    return (provider or "google").strip().lower()


# ─── PLUMBING ─────────────────────────────────────────────────────

def _resolve_config(provider: str, config: dict | None) -> dict:
    """Merge user config with provider defaults + optional server env var."""
    meta = PROVIDERS.get(normalize_provider(provider), PROVIDERS["google"])
    config = dict(config or {})
    resolved = {
        "api_key": (config.get("api_key") or "").strip(),
        "base_url": (config.get("base_url") or meta.get("default_base_url") or "").strip(),
        "model": (config.get("model") or meta.get("default_model") or "").strip(),
        "prompt": (config.get("prompt") or "").strip(),
    }
    # Fall back to a server-side env var if the subtitler left the key blank
    if not resolved["api_key"] and meta.get("env_key"):
        resolved["api_key"] = os.getenv(meta["env_key"], "").strip()
    if not resolved["base_url"] and meta.get("custom_endpoint") and config.get("endpoint"):
        resolved["base_url"] = config.get("endpoint").strip()
    return resolved


def _source_target(source: str, target: str):
    """Return (source_for_prompt, target_for_prompt) language name strings."""
    src = (source or "").strip() or "auto-detect"
    tgt = (target or "").strip() or "English"
    return src, tgt


def _strip_preamble(text: str) -> str:
    """Remove common model chatter like 'Here is the translation:'."""
    t = text.strip()
    import re
    m = re.match(r"^(here\s*(is|'s)\s*)?[a-z ,]*translation\s*:\s*", t, re.I)
    if m:
        t = t[m.end():].strip()
    if t.startswith('"') and t.endswith('"') and len(t) > 1:
        t = t[1:-1].strip()
    return t


# ─── NETWORK CALLS ────────────────────────────────────────────────

def _post_json(url: str, payload: dict, headers: dict, timeout: float = 120.0):
    with httpx.Client(timeout=timeout) as client:
        r = client.post(url, json=payload, headers=headers)
    return r


def _translate_openai_compatible(text: str, resolved: dict, source: str, target: str) -> str:
    if not resolved["base_url"]:
        raise ValueError("A base URL is required for this provider.")
    prompt = resolved["prompt"] or DEFAULT_PROMPT.format(source=source, target=target)
    body = {
        "messages": [
            {"role": "system", "content": "You are a subtitle translation engine."},
            {"role": "user", "content": f"{prompt}\n\n{text}"},
        ],
        "temperature": 0.3,
    }
    if resolved["model"]:
        body["model"] = resolved["model"]
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if resolved["api_key"]:
        headers["Authorization"] = "Bearer " + resolved["api_key"]
    url = resolved["base_url"].rstrip("/") + "/chat/completions"
    r = _post_json(url, body, headers)
    if r.status_code != 200:
        raise RuntimeError(f"Provider error {r.status_code}: {r.text[:300]}")
    data = r.json()
    return data["choices"][0]["message"]["content"]


def _translate_anthropic(text: str, resolved: dict, source: str, target: str) -> str:
    if not resolved["api_key"]:
        raise ValueError("An Anthropic API key is required.")
    if not resolved["model"]:
        raise ValueError("A model name is required for Anthropic.")
    prompt = resolved["prompt"] or DEFAULT_PROMPT.format(source=source, target=target)
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": resolved["api_key"],
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    body = {
        "model": resolved["model"],
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": f"{prompt}\n\n{text}"}],
    }
    r = _post_json(url, body, headers)
    if r.status_code != 200:
        raise RuntimeError(f"Anthropic error {r.status_code}: {r.text[:300]}")
    data = r.json()
    return "".join(p.get("text", "") for p in data.get("content", []))


def _translate_gemini(text: str, resolved: dict, source: str, target: str) -> str:
    if not resolved["api_key"]:
        raise ValueError("A Gemini API key is required.")
    if not resolved["model"]:
        raise ValueError("A model name is required for Gemini.")
    prompt = resolved["prompt"] or DEFAULT_PROMPT.format(source=source, target=target)
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{resolved['model']}:generateContent?key={resolved['api_key']}")
    body = {
        "contents": [{"parts": [{"text": f"{prompt}\n\n{text}"}]}],
        "generationConfig": {"temperature": 0.3},
    }
    r = _post_json(url, body, {"Content-Type": "application/json"})
    if r.status_code != 200:
        raise RuntimeError(f"Gemini error {r.status_code}: {r.text[:300]}")
    data = r.json()
    cand = (data.get("candidates") or [{}])[0]
    parts = cand.get("content", {}).get("parts", [])
    return "".join(p.get("text", "") for p in parts)


def _translate_deepl(text: str, resolved: dict, source: str, target: str) -> str:
    if not resolved["api_key"]:
        raise ValueError("A DeepL API key is required.")
    base = resolved["base_url"] or "https://api-free.deepl.com/v2"
    src = _code(source, _DEEPL_LANG)
    tgt = _code(target, _DEEPL_LANG)
    params = {"target_lang": tgt.upper()}
    if source and source.lower() not in ("auto", "auto-detect", ""):
        params["source_lang"] = src.upper()
    headers = {
        "Authorization": "DeepL-Auth-Key " + resolved["api_key"],
        "Content-Type": "application/json",
    }
    r = _post_json(base.rstrip("/") + "/translate",
                   {"text": [text], **params}, headers)
    if r.status_code != 200:
        raise RuntimeError(f"DeepL error {r.status_code}: {r.text[:300]}")
    data = r.json()
    return data["translations"][0]["text"]


def _translate_libretranslate(text: str, resolved: dict, source: str, target: str) -> str:
    base = resolved["base_url"] or "http://localhost:5000"
    src = _code(source, _GOOGLE_LANG)
    tgt = _code(target, _GOOGLE_LANG)
    payload = {"q": text, "source": src, "target": tgt, "format": "text"}
    if resolved["api_key"]:
        payload["api_key"] = resolved["api_key"]
    headers = {"Content-Type": "application/json"}
    r = _post_json(base.rstrip("/") + "/translate", payload, headers)
    if r.status_code != 200:
        raise RuntimeError(f"LibreTranslate error {r.status_code}: {r.text[:300]}")
    data = r.json()
    return data.get("translatedText", "")


def _translate_microsoft(text: str, resolved: dict, source: str, target: str) -> str:
    if not resolved["api_key"]:
        raise ValueError("An Azure Translator key is required.")
    region = resolved["base_url"] or "eastus"
    tgt = _code(target, _GOOGLE_LANG)
    src = _code(source, _GOOGLE_LANG)
    url = (f"https://{region}.api.cognitive.microsoft.com/translator/text/v3.0/"
           f"translate?api-version=3.0&to={tgt}")
    if source and source.lower() not in ("auto", "auto-detect", ""):
        url += f"&from={src}"
    headers = {
        "Ocp-Apim-Subscription-Key": resolved["api_key"],
        "Ocp-Apim-Subscription-Key-Region": region,
        "Content-Type": "application/json",
    }
    r = _post_json(url, [{"Text": text}], headers)
    if r.status_code != 200:
        raise RuntimeError(f"Azure error {r.status_code}: {r.text[:300]}")
    data = r.json()
    return data[0]["translations"][0]["text"]


def _translate_google(text: str, target: str, source: str = "auto", retries: int = 2) -> str:
    import urllib.parse
    import urllib.request
    tgt = _code(target, _GOOGLE_LANG)
    src = _code(source, _GOOGLE_LANG) if source else "auto"
    url = (
        "https://translate.googleapis.com/translate_a/single"
        f"?client=gtx&sl={urllib.parse.quote(src)}&tl={urllib.parse.quote(tgt)}"
        f"&dt=t&q={urllib.parse.quote(text)}"
    )
    last_err = None
    for _ in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return "".join(seg[0] for seg in data[0] if seg and seg[0])
        except Exception as e:
            last_err = e
            time.sleep(0.4)
    raise last_err or RuntimeError("google translate failed")


# ─── PUBLIC DISPATCH ──────────────────────────────────────────────

def translate_one(text: str, provider: str, config: dict | None,
                  source_lang: str = "", target_lang: str = "English") -> str:
    """
    Translate a single line. Falls back to the original text on any failure
    (the caller decides whether to keep or drop failures).
    """
    provider = normalize_provider(provider)
    meta = PROVIDERS.get(provider, PROVIDERS["google"])
    kind = meta["kind"]
    src, tgt = _source_target(source_lang, target_lang)

    if kind == "google":
        return _translate_google(text, tgt, src if src != "auto-detect" else "auto")

    resolved = _resolve_config(provider, config)

    # AI/chat providers: require at least a key (unless key-less local).
    if meta["needs_key"] and not resolved["api_key"]:
        raise ValueError(f"{meta['name']} requires an API key (paste it in the translate settings).")

    if kind == "openai_compatible":
        out = _translate_openai_compatible(text, resolved, src, tgt)
    elif kind == "anthropic":
        out = _translate_anthropic(text, resolved, src, tgt)
    elif kind == "gemini":
        out = _translate_gemini(text, resolved, src, tgt)
    elif kind == "deepl":
        out = _translate_deepl(text, resolved, src, tgt)
    elif kind == "libretranslate":
        out = _translate_libretranslate(text, resolved, src, tgt)
    elif kind == "microsoft":
        out = _translate_microsoft(text, resolved, src, tgt)
    else:
        return _translate_google(text, tgt, src if src != "auto-detect" else "auto")

    return _strip_preamble(out).strip()


# ─── BATCH + STREAMING (used by the editor routes) ────────────────

def translate_subtitles(subs: list, target_lang: str, source_lang: str = "",
                        provider: str = "google", config: dict | None = None) -> list:
    """Translate every subtitle's text. Returns a new list with translated `text`."""
    out = [dict(s) for s in subs]
    non_empty = [(i, s.get("text", "")) for i, s in enumerate(subs) if s.get("text", "").strip()]
    if not non_empty:
        return out
    for orig_i, text in non_empty:
        try:
            out[orig_i]["text"] = translate_one(text, provider, config, source_lang, target_lang)
        except Exception as e:
            print(f"[TRANSLATE] line {orig_i} failed: {e}")
    return out


def translate_subtitles_stream(subs: list, target_lang: str, source_lang: str = "",
                               provider: str = "google", config: dict | None = None,
                               stop_check=None, stop_action=None):
    """
    Generator that translates line-by-line and yields SSE-style progress events
    so the UI can show a live "translating N / Total" popup (like Subtitle Edit).
    Mirrors the contract of the original editor.translate_subtitles_stream.
    """
    out = [dict(s) for s in subs]
    non_empty = [(i, s.get("text", "")) for i, s in enumerate(subs) if s.get("text", "").strip()]
    total = len(non_empty)

    def _finish_stopped():
        action = stop_action() if callable(stop_action) else "apply"
        if action == "remove":
            return {"type": "stopped", "action": "remove", "subtitles": [dict(s) for s in subs]}
        return {"type": "stopped", "action": "apply", "subtitles": out}

    if not non_empty:
        yield {"type": "progress", "done": 0, "total": 0}
        yield {"type": "done", "subtitles": out}
        return

    provider = normalize_provider(provider)
    done = 0
    for orig_i, text in non_empty:
        if stop_check is not None and stop_check():
            yield _finish_stopped()
            return
        translated = text
        try:
            translated = translate_one(text, provider, config, source_lang, target_lang)
            out[orig_i]["text"] = translated
        except Exception as e:
            print(f"[TRANSLATE] line {orig_i} failed: {e}")
        done += 1
        yield {"type": "line", "done": done, "total": total,
               "original": text, "translated": translated}
        if done % 5 == 0:
            if stop_check is not None and stop_check():
                yield _finish_stopped()
                return
            # Politeness delay for free/rate-limited endpoints
            if provider in ("google", "libretranslate"):
                time.sleep(0.25)

    yield {"type": "done", "subtitles": out}
