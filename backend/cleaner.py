# cleaner.py — AI subtitle cleaner
# Supports: LM Studio (local, no limits) or Groq (cloud, free tier)

import os
import json
import re
import time
from dotenv import load_dotenv
from platform_rules import get_platform

load_dotenv()


# ─── LLM CLIENT FACTORY ──────────────────────────────────────────────────────

def _get_client_and_model():
    """Returns (client, model_name, is_local) based on LLM_PROVIDER env var."""
    provider = os.getenv("LLM_PROVIDER", "groq").lower()

    if provider == "lmstudio":
        from openai import OpenAI
        url = os.getenv("LM_STUDIO_URL", "http://localhost:1234/v1")
        model = os.getenv("LM_STUDIO_MODEL", "gemma-3-4b-it")
        client = OpenAI(base_url=url, api_key="lm-studio")  # key is ignored locally
        print(f"[LLM] Using LM Studio: {url} | model: {model}")
        return client, model, True

    else:  # groq
        from groq import Groq
        client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        model = "llama-3.1-8b-instant"
        print(f"[LLM] Using Groq cloud | model: {model}")
        return client, model, False


# ─── PROMPT ──────────────────────────────────────────────────────────────────

def build_prompt(raw_text: str, structure: str, platform: dict, max_chars: int) -> tuple[str, str]:
    """Returns (system_prompt, user_prompt)"""

    system = (
        "You are a professional subtitle formatter. "
        "Your job is ONLY to fix spelling/punctuation, apply universal OTT guidelines, "
        "and ensure no line exceeds the max character limit. "
        "Do NOT use JSON. Return ONLY a bulleted list."
    )

    rules_list = list(platform.get("rules", []))
    
    if platform.get("two_speaker_format") == "hyphen_no_space":
        rules_list.append("Two speakers: begin each line with a hyphen without space (-Speaker).")
    elif platform.get("two_speaker_format") == "hyphen_with_space":
        rules_list.append("Two speakers: begin each line with a hyphen with space (- Speaker).")
        
    if "profanity_format" in platform:
        rules_list.append(f"Format profanity as: {platform['profanity_format']}")
        
    profanity_table = platform.get("profanity_table", {})
    if profanity_table:
        replacements = ", ".join([f"{k} -> {v}" for k, v in profanity_table.items()])
        rules_list.append(f"Replace profanity according to this list: {replacements}")
        
    remove_elements = platform.get("remove_elements", [])
    if remove_elements:
        rules_list.append(f"Remove the following elements completely from the text: {', '.join(remove_elements)}")

    platform_rules_str = "\n".join([f"- {r}" for r in rules_list])

    user = f"""Platform: {platform.get('name')} | Max chars per line: {max_chars}

Universal Rules:
- DO NOT remove any dialogue unless it is a filler (ugh, hmm, erm, ah, oh) or stage direction.
- Fix spelling, grammar, and punctuation. Standard US English spelling.
- If a dialogue is longer than {max_chars} characters, you MUST insert a literal "\\n" (backslash n) at a natural pause to split it into two lines.
- No single line within the subtitle should ever exceed {max_chars} characters.
- Remove all Hard-of-Hearing (HOH) elements, scene descriptions, and stage directions.
- Use double hyphens (--) for interrupted sentences.
- Use ellipses (...) for trail offs and long pauses.

Platform Specific Rules:
{platform_rules_str}

INPUT:
---
{raw_text}
---

Return ONLY a bulleted list with a hyphen (-). Do not write anything else:
- formatted line 1
- formatted line 2\\nsecond part of line 2"""

    return system, user


# ─── JSON REPAIR ─────────────────────────────────────────────────────────────

def _extract_lines(text: str) -> list[str] | None:
    """Try multiple strategies to get dialogue lines from AI response."""
    if not text or not text.strip():
        return []  # empty response = no dialogue in this chunk

    # Strategy 1: direct parse
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "lines" in data:
            return [l for l in data["lines"] if isinstance(l, str) and l.strip()]
        if isinstance(data, list):
            return [str(l) for l in data if str(l).strip()]
    except Exception:
        pass

    # Strategy 2: strip markdown fences
    cleaned = re.sub(r"```(?:json)?\s*", "", text).strip()
    cleaned = re.sub(r"```\s*$", "", cleaned).strip()
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict) and "lines" in data:
            return [l for l in data["lines"] if isinstance(l, str) and l.strip()]
        if isinstance(data, list):
            return [str(l) for l in data if str(l).strip()]
    except Exception:
        pass

    # Strategy 3: extract outermost { }
    match = re.search(r'\{.*\}', cleaned, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
            if isinstance(data, dict) and "lines" in data:
                return [l for l in data["lines"] if isinstance(l, str) and l.strip()]
        except Exception:
            pass

    # Strategy 4: extract [ ] array
    match = re.search(r'\[.*\]', cleaned, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
            if isinstance(data, list):
                return [str(l) for l in data if str(l).strip()]
        except Exception:
            pass

    # Strategy 5: extract quoted strings (handles partial/truncated JSON)
    strings = re.findall(r'"((?:[^"\\]|\\.){3,})"', cleaned)
    skip = {"lines", "subtitles", "stats", "text", "id", "platform", "true", "false"}
    candidates = [s.replace('\\"', '"').replace('\\n', '\n')
                  for s in strings if s.lower() not in skip and len(s) > 5]
    if candidates:
        return candidates

    return None  # truly unparseable


# ─── MAIN CLEANER ────────────────────────────────────────────────────────────

def clean_subtitle_chunk(
    raw_text: str,
    structure: str,
    platform_key: str,
    filename: str
) -> list[dict]:
    """
    Clean a single chunk using PURE PYTHON (No LLM).
    Since extractor.py already extracted the dialogue perfectly, we just format it.
    """
    platform = get_platform(platform_key)
    max_chars = platform.get("max_chars_per_line", 42)

    # 1. Skip chunks with no meaningful content
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    if not lines:
        return []

    client, model_name, is_local = _get_client_and_model()
    system_prompt, user_prompt = build_prompt(raw_text, structure, platform, max_chars)

    # Ultra-fast parallel trick:
    # 600-char chunk is ~150 input tokens.
    # We only need ~150 output tokens. We cap at 300 to be safe.
    # Total request size = ~450 tokens. 
    # With Groq's 6000 TPM limit, 450 tokens per request means we can do 10+ chunks in parallel!
    max_output_tokens = 800 if is_local else 300
    retry_delay = 0.5 if is_local else 2

    last_error = None

    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.2,
                max_tokens=max_output_tokens,
            )
            choice = response.choices[0]
            result_text = (choice.message.content or "").strip()
            finish_reason = choice.finish_reason
            
            print(f"[DEBUG attempt {attempt+1}] Prompt length: {len(system_prompt) + len(user_prompt)} chars")
            print(f"[DEBUG attempt {attempt+1}] finish_reason={finish_reason} | response (first 400): {result_text[:400]!r}")

            if not result_text:
                return []

            def _auto_break_line(text: str, mx: int) -> str:
                if len(text) <= mx:
                    return text
                paras = text.split('\n')
                final = []
                for p in paras:
                    if len(p) <= mx:
                        final.append(p)
                        continue
                    words = p.split()
                    cur = []
                    cur_len = 0
                    for w in words:
                        if cur_len + len(w) + (1 if cur else 0) <= mx:
                            cur.append(w)
                            cur_len += len(w) + (1 if cur else 0)
                        else:
                            if cur:
                                final.append(" ".join(cur))
                            cur = [w]
                            cur_len = len(w)
                    if cur:
                        final.append(" ".join(cur))
                return "\n".join(final)

            # Parse bullet points instead of JSON
            extracted_lines = []
            for line in result_text.splitlines():
                line = line.strip()
                if line.startswith("-") or line.startswith("*"):
                    # Remove the bullet and leading spaces
                    cleaned_line = re.sub(r'^[-*]\s*', '', line).strip()
                    cleaned_line = cleaned_line.replace('\\n', '\n')
                    cleaned_line = _auto_break_line(cleaned_line, max_chars)
                    extracted_lines.append(cleaned_line)
                elif line:
                    cleaned_line = line.replace('\\n', '\n')
                    cleaned_line = _auto_break_line(cleaned_line, max_chars)
                    extracted_lines.append(cleaned_line)

            if not extracted_lines:
                last_error = Exception("No bullet points extracted")
                time.sleep(retry_delay)
                continue

            subtitles = []
            for i, line in enumerate(extracted_lines):
                if not line:
                    continue
                flagged = False
                flag_reason = ""
                for ln in line.split("\n"):
                    if len(ln) > max_chars:
                        flagged = True
                        flag_reason = f"Line too long ({len(ln)} chars, max {max_chars})"
                        break
                subtitles.append({
                    "id": i + 1,
                    "start_time": "",
                    "end_time": "",
                    "text": line,
                    "flagged": flagged,
                    "flag_reason": flag_reason
                })

            return subtitles

        except Exception as e:
            error_str = str(e).lower()
            print(f"Attempt {attempt+1} failed: {e}")
            last_error = e

            if "rate limit" in error_str or "429" in error_str:
                # Groq tells us exactly how long to wait (e.g. "try again in 4.13s")
                wait_time = 5.0
                match = re.search(r'try again in ([\d\.]+)s', error_str)
                if match:
                    wait_time = float(match.group(1)) + 0.5 # Add half a second buffer
                print(f"[INFO] Rate limit reached. Waiting exactly {wait_time:.2f}s...")
                time.sleep(wait_time)
            else:
                time.sleep(2)

    raise Exception(str(last_error) if last_error else "All attempts failed")


def clean_subtitle_file(
    raw_text: str,
    structure: str,
    platform_key: str,
    filename: str
) -> dict:
    """Legacy single-call wrapper."""
    platform = get_platform(platform_key)
    subtitles = clean_subtitle_chunk(raw_text, structure, platform_key, filename)
    return {
        "subtitles": subtitles,
        "stats": {
            "total_lines": len(subtitles),
            "flagged_lines": sum(1 for s in subtitles if s.get("flagged")),
            "platform": platform_key,
            "detected_structure": structure,
            "original_format": filename
        }
    }


def _error_result(platform_key, structure, filename, error_msg):
    return {
        "subtitles": [],
        "stats": {
            "total_lines": 0, "flagged_lines": 0,
            "platform": platform_key,
            "detected_structure": structure,
            "original_format": filename
        },
        "error": error_msg
    }


# ─── PLATFORM RULE EXTRACTOR ─────────────────────────────────────────────────

def extract_platform_rules_with_ai(guidelines_text: str, platform_name: str) -> dict:
    """Extract rules from a custom platform guidelines document."""
    client, model_name, _ = _get_client_and_model()

    prompt = f"""Read this subtitle guidelines document for "{platform_name}" and extract key rules.

Return ONLY valid JSON:
{{
  "name": "{platform_name}",
  "max_chars_per_line": 42,
  "max_lines": 2,
  "min_duration_seconds": 1.0,
  "max_duration_seconds": 7.0,
  "min_interval_seconds": 0.02,
  "reading_speed_target_cps": 17,
  "reading_speed_max_cps": 21,
  "file_format": "PAC",
  "two_speaker_format": "hyphen_no_space",
  "zero_subtitle_required": true,
  "rules": ["Rule 1", "Rule 2"],
  "summary": "One sentence summary"
}}

DOCUMENT:
---
{guidelines_text[:4000]}
---"""

    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=2000,
        )
        result_text = (response.choices[0].message.content or "").strip()
        cleaned = re.sub(r"```(?:json)?\s*", "", result_text).strip()
        match = re.search(r'\{.*\}', cleaned, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        print(f"[WARN] Platform rule extraction failed: {e}")

    return {
        "name": platform_name, "max_chars_per_line": 42, "max_lines": 2,
        "min_duration_seconds": 1.0, "max_duration_seconds": 7.0,
        "min_interval_seconds": 0.02, "reading_speed_target_cps": 17,
        "reading_speed_max_cps": 21, "file_format": "PAC",
        "two_speaker_format": "hyphen_no_space", "zero_subtitle_required": True,
        "rules": ["Maximum 42 characters per line", "Maximum 2 lines", "Standard guidelines"],
        "summary": f"Custom platform: {platform_name}"
    }
