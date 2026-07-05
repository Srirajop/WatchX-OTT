# cleaner.py - AI subtitle cleaner
# Supports: LM Studio (local, no limits) or Groq (cloud, free tier)

import os
import json
import re
import time
from dotenv import load_dotenv
from platform_rules import get_platform

load_dotenv()


# --- LLM CLIENT FACTORY ---

def _get_client_and_model():
    """Returns (client, model_name, is_local) based on LLM_PROVIDER env var."""
    provider = os.getenv("LLM_PROVIDER", "groq").lower()

    if provider == "lmstudio":
        from openai import OpenAI
        url = os.getenv("LM_STUDIO_URL", "http://localhost:1234/v1")
        model = os.getenv("LM_STUDIO_MODEL", "gemma-3-4b-it")
        client = OpenAI(base_url=url, api_key="lm-studio")
        print(f"[LLM] Using LM Studio: {url} | model: {model}")
        return client, model, True
    else:
        from groq import Groq
        client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        model = "llama-3.1-8b-instant"
        print(f"[LLM] Using Groq cloud | model: {model}")
        return client, model, False


# --- PROMPT BUILDER ---

def build_prompt(raw_text: str, structure: str, platform: dict, max_chars: int) -> tuple[str, str]:
    """
    Build a very explicit, actionable prompt so the LLM actually applies
    OTT platform rules (italics, hyphens, numbers, profanity etc.) not just grammar.
    Returns (system_prompt, user_prompt).
    """
    platform_name = platform.get("name", "Unknown")
    rules_text = " ".join(platform.get("rules", []))
    remove = platform.get("remove_elements", [])
    profanity_table = platform.get("profanity_table", {})

    system = (
        "You are a professional OTT subtitle editor at Iyuno Media Group. "
        "Your ONLY job is to apply the EXPLICITLY LISTED formatting rules to the dialogue text. "
        "This may include adding <i> italic tags, fixing hyphen speaker format, spelling out numbers, "
        "replacing profanity, removing HOH elements, and fixing punctuation. "
        "STRICT ANTI-HALLUCINATION RULES: "
        "(1) NEVER add formatting that is not explicitly required by the listed rules. "
        "(2) NEVER add <b> or </b> bold tags — bold is NEVER used in OTT subtitles. "
        "(3) NEVER change the meaning or content of the dialogue. "
        "(4) NEVER invent words, remove dialogue, or rewrite sentences. "
        "(5) Only apply italics (<i>...</i>) when a specific rule explicitly requires it. "
        "(6) If no italic rule applies, output plain text with NO tags whatsoever. "
        "Return ONLY a bulleted list. Never skip any rule. Never add commentary."
    )

    # Build numbered, actionable instructions
    instructions = []

    # 1. Line length
    instructions.append(
        f"LINE LENGTH: Each subtitle line must NOT exceed {max_chars} characters. "
        f"If a single dialogue entry exceeds {max_chars} chars, insert a literal \\n "
        f"at a natural phrase boundary to split it into 2 lines."
    )

    # 2. HOH/EMT removal
    if "HOH" in remove or "EMT" in remove:
        instructions.append(
            "DELETE COMPLETELY (Hard-of-Hearing/EMT elements - these must be removed, NOT kept): "
            "[MUSIC], [MUSIC PLAYING], [APPLAUSE], [LAUGHTER], [CHEERING], [GUNSHOT], [EXPLOSION], "
            "[SINGING], (music), (singing), (narrator), (narrating), (chuckles), (laughs), "
            "(sighs), (gasps), (crying), and ANY text inside square brackets [...] or "
            "parentheses (...) that describes a sound, action, or stage direction. "
            "If an entire subtitle is only a sound effect, return nothing for that entry - skip it."
        )
    elif "stage_directions" in remove:
        instructions.append(
            "DELETE stage directions: Remove ALL text inside parentheses (...) that describes "
            "an action or emotion like (whispering), (laughs), (on phone), (V.O.), etc. "
            "Keep only the spoken dialogue."
        )

    if "character_names" in remove:
        instructions.append(
            "DELETE character name labels: Remove names like 'JOHN:', 'MARY -', 'NARRATOR:' "
            "that appear before dialogue. Keep only the actual spoken words."
        )

    if "fillers" in remove:
        instructions.append(
            "DELETE filler words: Remove ugh, hmm, erm, um, uh, ah, oh (and variants like "
            "uhh, umm, ahhh) plus any comma or period directly after them."
        )

    # 3. Two-speaker hyphen format - CRITICAL
    speaker_fmt = platform.get("two_speaker_format", "")
    if speaker_fmt == "hyphen_no_space":
        instructions.append(
            "TWO SPEAKERS - HYPHEN WITHOUT SPACE: When two different speakers appear in one subtitle, "
            "start EACH speaker's line with a hyphen immediately touching the first word - NO space. "
            "CORRECT: -I said hello.\\n-She waved back. "
            "WRONG: - I said hello. "
            "This applies whenever dialogue switches speaker within one subtitle block."
        )
    elif speaker_fmt == "hyphen_with_space":
        instructions.append(
            "TWO SPEAKERS - HYPHEN WITH SPACE: When two speakers appear in one subtitle, "
            "start EACH speaker's line with a hyphen followed by ONE space then the word. "
            "CORRECT: - I said hello.\\n- She waved back. "
            "WRONG: -I said hello."
        )

    # 4. Interruptions and trail-offs
    instructions.append(
        "INTERRUPTIONS: Use -- (double hyphen, no spaces) when a sentence is cut off mid-way "
        "e.g. 'I was just going to--' or '--Never mind.' "
        "TRAIL-OFFS / PAUSES: Use ... (exactly 3 dots, no more, no less) when someone trails off "
        "or there's a long pause: 'I don't know...' "
        "NEVER use !! or ?? or !? or ?! - use only single ! or single ?."
    )

    # 5. Number rules
    if "1-10 in words" in rules_text or "Numbers 1-10" in rules_text:
        instructions.append(
            "NUMBERS: Write the numbers one through ten as words (one, two, three, four, five, "
            "six, seven, eight, nine, ten). Write 11 and above as numerals (11, 42, 1000). "
            "EXCEPTIONS: years (2024), addresses (42 Main St), time (3:00 PM), "
            "measurements (6ft, 50mph), percentages (5%) always stay as numerals."
        )
    elif "1-9" in rules_text or "spell out numbers 1-9" in rules_text.lower():
        instructions.append(
            "NUMBERS: Write one through nine as words. Ten (10) and above stay as numerals. "
            "EXCEPTIONS: years, addresses, time, measurements always use numerals."
        )
    elif "0-9 written out" in rules_text:
        instructions.append(
            "NUMBERS: Write zero through nine as words (zero, one, two... nine). "
            "10 and above stay as numerals."
        )

    # 6. ITALICS - the most important formatting rule
    no_italics_platforms = ["Nickelodeon", "TVB", "Scripps"]
    is_no_italics = any(p in platform_name for p in no_italics_platforms)

    if is_no_italics:
        instructions.append(
            "ITALICS: This platform does NOT allow italic formatting. "
            "Do NOT write any <i> or </i> tags. "
            "If the input already has <i> tags, remove them and keep just the plain text."
        )
    else:
        italic_cases = []
        if "song" in rules_text.lower() and "italic" in rules_text.lower():
            italic_cases.append(
                "SONG LYRICS: Any line that contains a music note symbol (like a song being sung) "
                "MUST be wrapped in <i>...</i> tags. "
                "Example: <i>La la la, singing in the rain</i> or <i>♪ Hold me close ♪</i>"
            )
        if "narrat" in rules_text.lower() and "italic" in rules_text.lower():
            italic_cases.append(
                "NARRATION / VOICE-OVER (VO): Lines spoken by a narrator or heard as voice-over "
                "MUST be wrapped in <i>...</i> tags. "
                "Example: <i>Three years later, the city had changed.</i>"
            )
        if "phone" in rules_text.lower() and "italic" in rules_text.lower():
            italic_cases.append(
                "PHONE / RADIO / TV / INTERCOM: Dialogue heard through a phone, radio, TV, "
                "or intercom MUST be in italics. "
                "Example: <i>Can you hear me now?</i>"
            )
        if "foreign" in rules_text.lower() and "italic" in rules_text.lower():
            italic_cases.append(
                "FOREIGN WORDS: Non-English words or phrases (French, Spanish, etc.) that are "
                "not common English loanwords MUST be in italics inline. "
                "Example: She said <i>voila</i> and smiled. "
                "Do NOT italicise common words like cafe, yoga, karma, naïve."
            )
        if "Disney" in platform_name:
            # Disney has very specific VO/narrator rules
            italic_cases.append(
                "OFF-SCREEN SOUNDS heard through speakers/device: Use italics. "
                "But off-camera dialogue (person just not visible on screen) does NOT get italics."
            )
        if italic_cases:
            instructions.append(
                "ITALICS - USE <i>...</i> HTML TAGS FOR THESE CASES:\n"
                + "\n".join(f"  {c}" for c in italic_cases)
                + "\n  IMPORTANT: Write actual <i> and </i> in the text output. "
                "Do NOT just describe the formatting - actually add the tags."
            )

    # CRITICAL: Anti-hallucination / plain text default rule
    instructions.insert(0,
        "PLAIN TEXT DEFAULT — CRITICAL: The dialogue text must remain PLAIN unless a specific rule "
        "below explicitly requires formatting. DO NOT add <i>, <b>, or any HTML tags unless "
        "a numbered rule below specifically mandates it. "
        "NEVER add <b>bold</b> tags — bold formatting does NOT exist in OTT subtitles. "
        "NEVER rewrite, paraphrase or change the meaning of any dialogue. "
        "ONLY fix what the rules explicitly say to fix."
    )

    # 7. Profanity
    if profanity_table:
        pairs = ", ".join(f"{k}=>{v}" for k, v in list(profanity_table.items())[:12])
        instructions.append(
            f"PROFANITY REPLACEMENT: Replace these exact words: {pairs}. "
            "Apply the same pattern to other forms: if fuck=>fxxx, then fucking=>fxxxing, "
            "fucked=>fxxxed, fucker=>fxxxer. Case-insensitive."
        )
    elif platform.get("profanity_format") == "bleep_asterisk":
        instructions.append(
            "PROFANITY (BLEEP): Replace bleeped/censored words with *bleep* in lowercase. "
            "If it starts a sentence, use *Bleep* (capital B)."
        )
    elif platform.get("profanity_format") == "xxx":
        instructions.append(
            "PROFANITY (XXX FORMAT): Replace profanity with xxx censoring: "
            "fuck=>fxxx, cunt=>cxxx, pussy=>pxxx, shit=>sxxx, cock=>cxxx, bitch=>bxxx. "
            "Apply to all word forms."
        )

    if "asterisks (****)" in rules_text:
        instructions.append(
            "BEEPED PROFANITY: If there is beeped/censored audio, use exactly four asterisks (****) to represent it."
        )

    if "subtitling by iyuno" in rules_text.lower():
        instructions.append(
            "END CREDIT: You MUST add a final subtitle line that says exactly: 'Subtitling by Iyuno' at the very end of the dialogue."
        )

    # 8. Capitalisation
    instructions.append(
        "CAPITALISATION: Start every subtitle line with a capital letter. "
        "Exception: if a line begins with ... (ellipsis continuing previous thought), "
        "the first letter after ... may be lowercase: ...still waiting."
    )

    # 9. Punctuation
    instructions.append(
        "PUNCTUATION FIXES (apply all):\n"
        "  - Remove spaces before punctuation: 'hello .' => 'hello.'\n"
        "  - Replace !! or !!! with single !\n"
        "  - Replace ?? or ??? with single ?\n"
        "  - Replace !? or ?! with single !\n"
        "  - Replace .... or ..... with ... (always exactly 3 dots for ellipsis)\n"
        "  - Remove double spaces\n"
        "  - No period at end of a line if the sentence continues on the next subtitle"
    )

    # 10. Acronyms
    if any(x in rules_text for x in ["FBI", "BBC", "CIA", "Acronym", "acronym"]):
        instructions.append(
            "ACRONYMS: Write without periods between letters. "
            "FBI not F.B.I., NASA not N.A.S.A., CIA not C.I.A., NATO not N.A.T.O."
        )

    # 11. US English
    instructions.append(
        "US ENGLISH SPELLING: Use American spelling throughout. "
        "Examples: color (not colour), realize (not realise), favorite (not favourite), "
        "theater (not theatre), center (not centre)."
    )

    # 12. Song title formatting
    if "song titles" in rules_text.lower() or "song" in rules_text.lower():
        instructions.append(
            "SONG TITLES: Put song titles in double quotation marks: \"Bohemian Rhapsody\". "
            "Actual sung lyrics go in italics: <i>Is this the real life?</i>"
        )

    # 13. RAW PLATFORM RULES
    raw_rules = platform.get("rules", [])
    if raw_rules:
        rules_bulleted = "\n".join(f"  - {r}" for r in raw_rules)
        instructions.append(
            f"STRICT PLATFORM-SPECIFIC RULES (You MUST apply these where relevant):\n{rules_bulleted}"
        )

    instructions_str = "\n\n".join(
        f"RULE {i+1}: {inst}" for i, inst in enumerate(instructions)
    )

    user = f"""Platform for delivery: {platform_name} | Max characters per line: {max_chars}

MANDATORY FORMATTING RULES — APPLY ALL OF THEM:
{instructions_str}

INPUT DIALOGUE TO FORMAT:
---
{raw_text}
---

OUTPUT INSTRUCTIONS:
- Return ONLY a bulleted list, one hyphen (-) per subtitle line.
- Apply EVERY rule above to each line.
- If a line must be split due to length, use \\n between the two parts in the same bullet.
- If an entire entry is ONLY a sound effect or HOH element to delete, skip it entirely.
- Do NOT add any commentary, headers, notes, or explanation.
- ACTUALLY write <i>text</i> tags in your output ONLY when a rule above says to use italics.
- NEVER write <b>text</b> bold tags — these are NEVER allowed in OTT subtitles.
- NEVER change the spoken words — only fix formatting, punctuation, and style.
- ACTUALLY write -Word (or - Word) for two-speaker lines when the rule requires it.
- When in doubt: output plain text.

Example of correct output for a Disney platform:
- two, three
- -Wait, where are you going?\\n-I don't know...
- <i>♪ She loves you, yeah yeah yeah ♪</i>
- He was a fxxxing mess."""

    return system, user


# --- MAIN CLEANER ---

def clean_subtitle_chunk(
    raw_text: str,
    structure: str,
    platform_key: str,
    filename: str
) -> list[dict]:
    """
    Clean a single chunk of subtitle text using LLM.
    Sends explicit per-platform formatting instructions.
    """
    platform = get_platform(platform_key)
    max_chars = platform.get("max_chars_per_line", 42)

    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    if not lines:
        return []

    client, model_name, is_local = _get_client_and_model()
    system_prompt, user_prompt = build_prompt(raw_text, structure, platform, max_chars)

    max_output_tokens = 800 if is_local else 1200
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
                temperature=0.15,   # lower temp = more deterministic rule following
                max_tokens=max_output_tokens,
            )
            choice = response.choices[0]
            result_text = (choice.message.content or "").strip()
            finish_reason = choice.finish_reason

            print(f"[DEBUG attempt {attempt+1}] Prompt chars: {len(system_prompt)+len(user_prompt)}")
            print(f"[DEBUG attempt {attempt+1}] finish_reason={finish_reason} | response[:400]: {result_text[:400]!r}")

            if not result_text:
                return []

            def _auto_break_line(text: str, mx: int) -> str:
                """Ensure no single line exceeds mx chars."""
                if len(re.sub(r'<[^>]+>', '', text)) <= mx:
                    return text
                paras = text.split('\n')
                final = []
                for p in paras:
                    clean_p = re.sub(r'<[^>]+>', '', p)
                    if len(clean_p) <= mx:
                        final.append(p)
                        continue
                    # Try to split preserving italics
                    words = p.split()
                    cur, cur_len = [], 0
                    for w in words:
                        w_clean = re.sub(r'<[^>]+>', '', w)
                        if cur_len + len(w_clean) + (1 if cur else 0) <= mx:
                            cur.append(w)
                            cur_len += len(w_clean) + (1 if cur else 0)
                        else:
                            if cur:
                                final.append(" ".join(cur))
                            cur = [w]
                            cur_len = len(w_clean)
                    if cur:
                        final.append(" ".join(cur))
                return "\n".join(final)

            # Parse the bulleted list response
            extracted_lines = []
            for line in result_text.splitlines():
                line = line.strip()
                if not line:
                    continue
                # Remove bullet marker (- or *)
                if line.startswith("-") or line.startswith("*"):
                    # Only strip the FIRST bullet — two-speaker lines start with - too
                    # Check if this is a bullet (single - at start) vs a two-speaker line
                    # A real bullet has a space after: "- text" while two-speaker is "-text"
                    if len(line) > 1 and line[1] == " ":
                        cleaned_line = line[2:].strip()
                    elif len(line) > 1 and line[1] == "*":
                        cleaned_line = re.sub(r'^[*-]+\s*', '', line).strip()
                    else:
                        # Could be "-Speaker says this" two-speaker format — keep as-is
                        cleaned_line = line
                else:
                    cleaned_line = line

                # Convert escaped newlines to real newlines
                cleaned_line = cleaned_line.replace('\\n', '\n')
                # Auto-enforce line length
                cleaned_line = _auto_break_line(cleaned_line, max_chars)
                if cleaned_line.strip():
                    extracted_lines.append(cleaned_line)

            if not extracted_lines:
                last_error = Exception("No lines extracted from LLM response")
                time.sleep(retry_delay)
                continue

            subtitles = []
            for i, line in enumerate(extracted_lines):
                if not line.strip():
                    continue
                flagged = False
                flag_reason = ""
                for ln in line.split("\n"):
                    clean_ln = re.sub(r'<[^>]+>', '', ln)
                    if len(clean_ln) > max_chars:
                        flagged = True
                        flag_reason = f"Line too long ({len(clean_ln)} chars, max {max_chars})"
                        break
                subtitles.append({
                    "id": i + 1,
                    "start_time": "",
                    "end_time": "",
                    "original_text": lines[i] if i < len(lines) else line,
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
                wait_time = 5.0
                match = re.search(r'try again in ([\d\.]+)s', error_str)
                if match:
                    wait_time = float(match.group(1)) + 0.5
                print(f"[INFO] Rate limit reached. Waiting {wait_time:.2f}s...")
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


# --- PLATFORM RULE EXTRACTOR ---


def _repair_truncated_json(text: str) -> str:
    """
    Attempt to close a JSON object/array that was cut off by a token limit.
    Closes any unclosed strings, arrays, and objects so json.loads can succeed.
    """
    # Count open/close braces and brackets
    in_string = False
    escape_next = False
    depth_brace = 0
    depth_bracket = 0
    result = list(text)

    for ch in text:
        if escape_next:
            escape_next = False
            continue
        if ch == '\\':
            escape_next = True
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
            continue
        if not in_string:
            if ch == '{':
                depth_brace += 1
            elif ch == '}':
                depth_brace -= 1
            elif ch == '[':
                depth_bracket += 1
            elif ch == ']':
                depth_bracket -= 1

    # If we're still inside a string, close it
    suffix = ''
    if in_string:
        suffix += '"'
    # Close open arrays and objects
    suffix += ']' * depth_bracket
    suffix += '}' * depth_brace
    return text + suffix


def _call_llm_for_rules(client, model_name: str, platform_name: str, chunk: str) -> list:
    """
    Call LLM for a single chunk of guidelines text.
    Returns list of rule strings extracted from this chunk.
    """
    prompt = f"""Read this section of subtitle guidelines for "{platform_name}".

YOUR TASK:
Extract EVERY distinct rule or instruction you can find, but categorize them into two groups.
Return a JSON object with two arrays of strings.

{{
    "script_rules": [],      // Rules about textual formatting, grammar, punctuation, line limits, reading speed, quotes, italics, casing.
    "subtitler_rules": []    // Operational rules for human subtitlers (e.g. frame rates, timecode formats, syncing, positioning, file delivery).
}}

RULES FOR EXTRACTION:
- Extract EVERY distinct rule you can find — do not skip any.
- Include specific numeric limits (character counts, duration, CPS, etc.) in full.
- Each item must be one complete, self-contained rule sentence.
- Do not include markdown code blocks. Return ONLY the raw JSON object.

GUIDELINES SECTION:
---
{chunk}
---"""

    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=3000,
        )
        result_text = (response.choices[0].message.content or "").strip()
        # Strip markdown code fences
        result_text = re.sub(r"```(?:json)?\s*", "", result_text).strip().rstrip("`")
        # Try direct parse first
        try:
            parsed = json.loads(result_text)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        # Try repairing truncated JSON
        try:
            repaired = _repair_truncated_json(result_text)
            parsed = json.loads(repaired)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    except Exception as e:
        print(f"[RULES ERROR] LLM call failed: {e}")
    return {"script_rules": [], "subtitler_rules": []}


def _call_llm_for_metadata(client, model_name: str, platform_name: str, sample: str) -> dict:
    """
    Extract numeric/structural metadata from the guidelines document.
    Returns a dict with numeric fields.
    """
    prompt = f"""Read this subtitle guidelines document excerpt for "{platform_name}" and extract the numeric/structural metadata.

Return ONLY valid JSON (no comments, no markdown):
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
  "summary": "One sentence summary of this platform's subtitle style"
}}

DOCUMENT EXCERPT:
---
{sample[:3000]}
---"""

    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=800,
        )
        result_text = (response.choices[0].message.content or "").strip()
        result_text = re.sub(r"```(?:json)?\s*", "", result_text).strip().rstrip("`")
        match = re.search(r'\{.*\}', result_text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                repaired = _repair_truncated_json(match.group())
                return json.loads(repaired)
    except Exception as e:
        print(f"[WARN] LLM metadata extraction failed: {e}")
    return {}


def extract_platform_rules_with_ai(guidelines_text: str, platform_name: str) -> dict:
    """
    Extract ALL rules from a custom platform guidelines document.

    Strategy:
    1. Split the document into ~6000-char chunks (no arbitrary 4000-char cutoff).
    2. Run each chunk through the LLM independently to extract a flat rules array.
    3. De-duplicate and merge all rules from all chunks.
    4. Run a second LLM pass on the first chunk to extract numeric metadata
       (char limits, duration, CPS, file format, etc.).
    5. Combine metadata + merged rules into the final platform dict.
    """
    CHUNK_SIZE = 6000
    client, model_name, _ = _get_client_and_model()

    default = {
        "name": platform_name, "max_chars_per_line": 42, "max_lines": 2,
        "min_duration_seconds": 1.0, "max_duration_seconds": 7.0,
        "min_interval_seconds": 0.02, "reading_speed_target_cps": 17,
        "reading_speed_max_cps": 21, "file_format": "PAC",
        "two_speaker_format": "hyphen_no_space", "zero_subtitle_required": True,
        "rules": ["Maximum 42 characters per line", "Maximum 2 lines", "Standard guidelines"],
        "summary": f"Custom platform: {platform_name}"
    }

    if not guidelines_text or not guidelines_text.strip():
        return default

    # ── Step 1: chunk the document ──────────────────────────────────────────
    text = guidelines_text.strip()
    chunks = []
    start = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        # Try to break at a newline boundary to avoid mid-sentence splits
        if end < len(text):
            nl = text.rfind('\n', start, end)
            if nl > start:
                end = nl
        chunks.append(text[start:end])
        start = end

    print(f"[RULES] Extracting rules from {len(chunks)} chunk(s) for '{platform_name}'")

    # ── Step 2: extract rules from each chunk ───────────────────────────────
    all_script_rules = []
    all_subtitler_rules = []
    for i, chunk in enumerate(chunks):
        print(f"[RULES] Processing chunk {i+1}/{len(chunks)} ({len(chunk)} chars)")
        chunk_res = _call_llm_for_rules(client, model_name, platform_name, chunk)
        
        s_rules = chunk_res.get("script_rules", [])
        m_rules = chunk_res.get("subtitler_rules", [])
        print(f"[RULES] Chunk {i+1} yielded {len(s_rules)} script rules, {len(m_rules)} manual rules")
        
        if isinstance(s_rules, list): all_script_rules.extend(s_rules)
        if isinstance(m_rules, list): all_subtitler_rules.extend(m_rules)

    # ── Step 3: de-duplicate (case-insensitive, strip whitespace) ───────────
    def _dedup(rule_list):
        seen = set()
        out = []
        for r in rule_list:
            if not isinstance(r, str): continue
            key = r.strip().lower()
            if key and key not in seen:
                seen.add(key)
                out.append(r.strip())
        return out

    unique_script_rules = _dedup(all_script_rules)
    unique_subtitler_rules = _dedup(all_subtitler_rules)

    print(f"[RULES] Total unique script rules: {len(unique_script_rules)}, subtitler rules: {len(unique_subtitler_rules)}")

    if not unique_script_rules and not unique_subtitler_rules:
        # Fallback: return defaults so the platform is still saved
        return default

    # ── Step 4: extract numeric metadata from the first chunk ───────────────
    metadata = _call_llm_for_metadata(client, model_name, platform_name, chunks[0])

    # ── Step 5: merge ────────────────────────────────────────────────────────
    result = {
        "name":                     metadata.get("name", platform_name),
        "max_chars_per_line":       metadata.get("max_chars_per_line", 42),
        "max_lines":                metadata.get("max_lines", 2),
        "min_duration_seconds":     metadata.get("min_duration_seconds", 1.0),
        "max_duration_seconds":     metadata.get("max_duration_seconds", 7.0),
        "min_interval_seconds":     metadata.get("min_interval_seconds", 0.02),
        "reading_speed_target_cps": metadata.get("reading_speed_target_cps", 17),
        "reading_speed_max_cps":    metadata.get("reading_speed_max_cps", 21),
        "file_format":              metadata.get("file_format", "PAC"),
        "two_speaker_format":       metadata.get("two_speaker_format", "hyphen_no_space"),
        "zero_subtitle_required":   metadata.get("zero_subtitle_required", True),
        "summary":                  metadata.get("summary", f"Custom platform: {platform_name}"),
        "rules":                    unique_script_rules,
        "subtitler_rules":          unique_subtitler_rules,
    }
    return result
