# cleaner.py - AI subtitle cleaner
# Supports: LM Studio (local, no limits) or Groq (cloud, free tier)

import os
import json
import re
import time
from dotenv import load_dotenv
from platform_rules import get_platform

load_dotenv()


# ─── SUBTITLER-OPERATIONAL RULE FILTER ────────────────────────────────────────
# This tool does MORE than text cleaning. The "subtitler_rules" bucket is NOT a
# "human-only / discard" pile — it is fed to the OPERATIONAL ENGINE
# (rule_segregation.segregate_rules + timecoded_subtitles.prepare_for_platform),
# which MACHINE-APPLIES timing/reading-speed/duration/gap/zero-subtitle work.
#
# So a rule belongs in subtitler_rules when it is about TIMING, READING-SPEED,
# DURATION, GAP, ZERO-SUBTITLE, POSITIONING, FONT, or FILE/DELIVERY. Anything that
# touches the words or punctuation of the dialogue must stay in script_rules.
#
# We therefore WHITELIST text-cleaning phrases that must NEVER be moved, even if
# they mention seconds/frames, and only move rules that clearly describe
# timing/position/font/file/delivery work.

# Phrases that prove a rule is a SCRIPT-CLEANING (text) rule → always keep in script.
_SCRIPT_TEXT_PHRASES = [
    "character", "line", "subtitle", "dialogue", "word", "punctuation",
    "capital", "case", "spell", "profanity", "italic", "hyphen", "speaker",
    "acronym", "ellipsis", "quotation", "apostrophe", "number", "digit",
    "symbol", "ampersand", "reading speed", "cps", "characters per second",
    "second per", "remove", "strip", "hoh", "emt", "music", "laughter",
    "stage direction", "filler", "slang", "foreign", "song lyric", "voice",
]

# Keywords that, on their own, signal a genuine SUBTITLER/TIMING task.
_SUBTITLER_OPERATIONAL_KEYWORDS = [
    "gts pro", "pac file", "timecode", "time code", "frame rate", "fps",
    "font size", "font colour", "font color", "font type", "font face",
    "positioning", "position subtitles", "raise subtitle", "lower subtitle",
    "centre-justified", "center-justified", "centre justified", "center justified",
    "bottom of screen", "top of screen", "overlap", "shot change",
    "file naming", "file name", "delivery", "deliverable", "export",
    "spellcheck", "spell check", "repo file", "repositioning",
    "zero subtitle", "zero-subtitle", "end credit file",
    "translator credit", "translated by", "subtitling by iyuno",
    "reading speed setting", "cps setting", "character per second setting",
    "minimum gap", "frame gap", "frame header", "frame tail",
    "in-time", "out-time", "cue in", "cue out", "spotting",
    "caption editor", "caption studio", "swift", "ezcap",
    "sync", "offset", "delay",
]

# Timing/positioning phrases that (without a text-cleaning whitelist hit) mean
# "this is about WHEN/WHERE the subtitle appears", i.e. a subtitler task.
_TIMING_POSITION_PHRASE = re.compile(
    r"\b(timecode|time code|frame rate|fps|frame gap|frame header|frame tail|"
    r"cue[- ]?in|cue[- ]?out|spotting|shot change|positioning|"
    r"raise|lower|centre|center|font|repo|reposition|deliver|naming|"
    r"in[- ]?time|out[- ]?time|head|tail|gap)\b",
    re.IGNORECASE
)


def _filter_script_rules(script_rules: list, subtitler_rules: list) -> tuple[list, list]:
    """
    Post-process LLM-returned rule lists with a STRICT, bidirectional re-bucket.

    Goal: the Subtitler (Human) bucket must contain ONLY genuine subtitler /
    operational tasks (timing, duration, gap, positioning, font, file/delivery,
    zero-subtitle, credits). ANY rule that touches the WORDS or PUNCTUATION of
    the dialogue — characters per line, max lines, casing, spelling, profanity,
    ellipsis, acronyms, italics, HOH/sound removal, reading-speed/CPS expressed
    as a text limit, etc. — belongs in script_rules even if it mentions
    seconds/frames. This is enforced in BOTH directions so the LLM can't leak a
    text-cleaning rule into the human bucket (or vice-versa).
    """
    clean_script = []
    clean_subtitler = []

    def _is_text_cleaning_rule(rule: str) -> bool:
        rule_lower = rule.lower()
        # A genuine text-cleaning rule is never moved out of script_rules.
        if any(p in rule_lower for p in _SCRIPT_TEXT_PHRASES):
            return True
        # If it mentions neither a timing/operational keyword nor a
        # timing/position phrase, it's almost certainly a text rule.
        is_op = any(kw in rule_lower for kw in _SUBTITLER_OPERATIONAL_KEYWORDS)
        is_timing_pos = bool(_TIMING_POSITION_PHRASE.search(rule))
        return not (is_op or is_timing_pos)

    def _is_subtitler_rule(rule: str) -> bool:
        rule_lower = rule.lower()
        is_op = any(kw in rule_lower for kw in _SUBTITLER_OPERATIONAL_KEYWORDS)
        is_timing_pos = bool(_TIMING_POSITION_PHRASE.search(rule))
        return is_op or is_timing_pos

    for rule in (script_rules or []):
        if _is_text_cleaning_rule(rule) or not _is_subtitler_rule(rule):
            clean_script.append(rule)
        else:
            clean_subtitler.append(rule)

    for rule in (subtitler_rules or []):
        # Re-home any misclassified text-cleaning rule back to script_rules.
        if _is_text_cleaning_rule(rule):
            clean_script.append(rule)
        else:
            clean_subtitler.append(rule)

    return clean_script, clean_subtitler


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
        return client, model, False

def _rules_to_instructions(platform: dict) -> list[str]:
    """
    Map extracted platform rules into actionable instructions for the LLM.
    Ensures that generic instructions don't override specific platform rules.
    """
    rules = platform.get("rules", [])
    if not rules:
        return []
        
    instructions = []
    # Filter out rules already covered by hardcoded mechanics (like max_chars)
    for rule in rules:
        if "character" in rule.lower() or "maximum" in rule.lower():
            continue
        instructions.append(rule)
        
    return instructions

def build_prompt(raw_text: str, structure: str, platform: dict, max_chars: int) -> tuple[str, str]:
    """
    Build a very explicit, actionable prompt so the LLM actually applies
    OTT platform rules (italics, hyphens, numbers, profanity etc.) not just grammar.
    Returns (system_prompt, user_prompt).
    """
    platform_name = platform.get("name", "Unknown")
    remove = platform.get("remove_elements", [])
    
    subtitler_ops = platform.get("subtitler_rules", []) or []
    do_not_list = ""
    if subtitler_ops:
        do_not_sample = subtitler_ops[:8]  
        do_not_list = (
            " DO NOT attempt to perform any of these subtitler-only tasks "
            "(they are done in GTS Pro by the subtitler, not in the script): "
            + "; ".join(do_not_sample) + "."
        )

    system = (
        "You are a professional OTT subtitle editor at Iyuno Media Group. "
        "Your ONLY job is to apply the EXPLICITLY LISTED formatting rules to the dialogue text. "
        "This may include adding <i> italic tags, fixing hyphen speaker format, spelling out numbers, "
        "replacing profanity, removing HOH elements, and fixing punctuation."
        + do_not_list +
        " STRICT ANTI-HALLUCINATION RULES: "
        "(1) NEVER add formatting that is not explicitly required by the listed rules. "
        "(2) NEVER add <b> or </b> bold tags — bold is NEVER used in OTT subtitles. "
        "(3) NEVER change the meaning or content of the dialogue. "
        "(4) NEVER invent words, remove dialogue, or rewrite sentences. "
        "(5) Only apply italics (<i>...</i>) when a specific rule explicitly requires it. "
        "(6) If no italic rule applies, output plain text with NO tags whatsoever. "
        "Return ONLY a bulleted list. Never skip any rule. Never add commentary."
    )

    instructions = []
    instructions.append(
        f"LINE LENGTH: Each subtitle line must NOT exceed {max_chars} characters. "
        f"If a single dialogue entry exceeds {max_chars} chars, insert a literal \\n "
        f"at a natural phrase boundary to split it into 2 lines."
    )
    
    if "HOH" in remove or "EMT" in remove:
        instructions.append(
            "DELETE COMPLETELY (Hard-of-Hearing/EMT elements - these must be removed, NOT kept): "
            "[MUSIC], [MUSIC PLAYING], [APPLAUSE], [LAUGHTER], [CHEERING], [GUNSHOT], [EXPLOSION], "
            "[SINGING], (music), (singing), (narrator), (narrating), (chuckles), (laughs), "
            "(sighs), (gasps), (crying), and ANY text inside square brackets [...] or "
            "parentheses (...) that describes a sound, action, or stage direction. "
            "If an entire subtitle is only a sound effect, return nothing for that entry - skip it."
        )

    # Dynamic rules mapping
    dynamic_instructions = _rules_to_instructions(platform)
    for dyn in dynamic_instructions:
        instructions.append(dyn)
        
    instructions.insert(0,
        "PLAIN TEXT DEFAULT — CRITICAL: The dialogue text must remain PLAIN unless a specific rule "
        "below explicitly requires formatting. DO NOT add <i>, <b>, or any HTML tags unless "
        "a numbered rule below specifically mandates it. "
        "NEVER add <b>bold</b> tags — bold formatting does NOT exist in OTT subtitles. "
        "NEVER rewrite, paraphrase or change the meaning of any dialogue. "
        "ONLY fix what the rules explicitly say to fix."
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
"""
    return system, user

def clean_subtitle_chunk(
    raw_text: str,
    structure: str,
    platform_key: str = "generic",
    filename: str = ""
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
                # Remove bullet marker (- or *), but preserve two-speaker prefixes.
                # Rule: a BULLET is "- text" (dash-space-word).
                #       a TWO-SPEAKER line is "-Word" or "-Word\n-Word" (dash immediately touching word).
                if line.startswith("* "):
                    # Markdown bullet with asterisk — always a bullet marker
                    cleaned_line = line[2:].strip()
                elif line.startswith("- "):
                    # Dash-space: strip the bullet, but check if the content itself
                    # starts with another dash (two-speaker nested under a bullet).
                    content = line[2:].strip()
                    # Keep as-is — content may be "-Speaker1\n-Speaker2"
                    cleaned_line = content
                elif line.startswith("-") and len(line) > 1 and line[1] not in (' ', '-'):
                    # No space after dash: this IS a two-speaker prefix — keep whole line
                    cleaned_line = line
                elif line.startswith("**") or line.startswith("--"):
                    # Double marker — strip outer markers
                    cleaned_line = re.sub(r'^[*-]{2}\s*', '', line).strip()
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


def _normalize_rule_text(rule: str) -> str:
    """
    Turn a raw LLM rule fragment into a clean, properly-written rule sentence.

    - Strips the scaffolding the 8B model sometimes emits (verbatim quotes,
      JSON keys like 'rule:'/'verbatim_quote:', leading bullets/numbers).
    - Collapses whitespace, capitalises the first word, and removes any
      trailing period so the rule list reads uniformly.
    - Drops empty / junk results.
    """
    if not rule or not isinstance(rule, str):
        return ""
    text = rule.strip()
    if not text:
        return ""

    # Remove JSON-ish keys the model may have leaked:  "rule": "...",  "verbatim_quote": "..."
    text = re.sub(r'^\s*(?:rule|verbatim_quote|quote|category|type)\s*[:=]\s*', '', text, flags=re.IGNORECASE)
    # Remove wrapping quotes / brackets
    text = text.strip('"\'`{}[] ')
    # Strip a leading bullet or ordinal like "1." / "- " / "* "
    text = re.sub(r'^[\-\*•]\s*', '', text)
    text = re.sub(r'^\d+[\.\)]\s*', '', text)
    # Remove any stray trailing quote fragments
    text = text.strip('"\'` ')
    text = re.sub(r'\s+', ' ', text).strip()
    if not text:
        return ""

    # Capitalise first alphabetic character
    m = re.search(r'[a-zA-Z]', text)
    if m and text[m.start()].islower():
        text = text[:m.start()] + text[m.start()].upper() + text[m.start() + 1:]

    # Drop a single trailing period (rules are list items, not sentences with full stops)
    if text.endswith('.'):
        text = text[:-1].strip()

    # Sanity: discard if it's basically just a quote fragment or too short
    if len(text) < 4:
        return ""
    return text


def _normalize_rule_list(rules: list) -> list:
    """Normalize + de-duplicate a list of rule strings into clean rule sentences."""
    out = []
    seen = set()
    for r in rules:
        if not isinstance(r, str):
            continue
        # If the model returned an object, pull the 'rule' field
        norm = _normalize_rule_text(r)
        if not norm:
            continue
        key = norm.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(norm)
    return out


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


def _call_llm_for_rules(client, model_name: str, platform_name: str, chunk: str) -> dict:
    """
    Call LLM for a single chunk of guidelines text.
    Returns a dict with extracted script and subtitler rules.
    """
    import json
    import re as _re

    prompt = f"""Read this section of subtitle guidelines for "{platform_name}".

YOUR TASK:
Extract EVERY distinct rule or instruction you can find, and categorize each into EXACTLY ONE of two groups based on what the tool's SCRIPT CLEANER can actually DO.

This tool's script cleaner is an AUTOMATED text formatter. It ONLY changes the DIALOGUE
TEXT of subtitles. Its actual, verified capabilities are:

SCRIPT-CLEANING CAPABILITIES (→ put these in "script_rules"):
  - Maximum characters per line / maximum number of lines per subtitle
  - Remove HOH / SDH / sound elements: [MUSIC], [LAUGHTER], (applause), etc.
  - Remove stage directions, scene descriptions, script annotations, (OPTIONAL) notes
  - Remove character / speaker name labels
  - Remove filler words (uh, hmm, er, um)
  - Replace profanity (per a profanity word list) or mask with asterisks (****)
  - Punctuation: fix double spaces, space-before-punctuation, double/mixed punctuation
  - Ellipsis normalised to three dots; leading ellipsis without a space
  - Two-speaker hyphen format (-Word vs "- Word")
  - Use quotation marks instead of apostrophes for quotes
  - No periods in acronyms (F.B.I. -> FBI)
  - Numbers spelled out in words (1-10, 0-9, or 1-9)
  - Sentence-case capitalisation
  - US / UK English spelling normalisation
  - Split long lines to fit the character / line limit
  - Italics for song lyrics, foreign words, narration / voice-over, phone / radio
  - Characters per second (CPS) / reading-speed LIMIT expressed as a text constraint
  - Removal of forbidden symbols (& < > degree copyright)

OPERATIONAL ENGINE (the tool MACHINE-APPLIES these — extract them as rules, do NOT
treat them as human-only):
  - Reading-speed / CPS → re-times subtitles so dialogue is readable at the limit
  - Minimum / maximum DURATION per subtitle
  - Minimum GAP / frame interval between subtitles
  - ZERO-SUBTITLE field (STORY: / LANG:) auto-inserted when required

  SUBTITLER / OPERATIONAL TASKS (→ put these in "subtitler_rules"):
  Our tool performs MORE than text cleaning — it also runs an operational engine
  that MACHINE-APPLIES the following, so they are NOT human-only:
  - Reading-speed / CPS limits, characters-per-second: the engine re-times each
    subtitle so the dialogue is readable at the required CPS.
  - Minimum / maximum DURATION of each subtitle (e.g. "min 5/6 second", "max 6s").
  - Minimum GAP / frame interval between consecutive subtitles (e.g. "2-frame gap").
  - ZERO-SUBTITLE field (STORY: / LANG:): the engine auto-inserts it when required.
  These TIMING rules must still be extracted (into subtitler_rules) — they are fed
  to the operational engine automatically; they are NOT discarded.

  Genuinely HUMAN-ONLY tasks (capture as notes, not text changes):
  - Positioning: top/bottom/centre justification, raising subtitles, overlap handling
    (placement in the NLE — recorded as a delivery note).
  - Font size / colour / type / face (a visual property of the deliverable).
  - File naming convention, file format (PAC, etc. — unless it also states a text rule).
  - Repo file / repositioning, end-credit file.
  - Translator / subtitling credit subtitles (the actual credit line).
  - Spellcheck pass.

  IMPORTANT — DO NOT put text-cleaning rules in subtitler_rules. Anything about
  the WORDS or PUNCTUATION of the dialogue (maximum characters per line, maximum
  number of lines, capitalisation/case, spelling, profanity, ellipsis, acronyms,
  italics, removal of [MUSIC]/[LAUGHTER]/HOH/sound cues, filler words, speaker
  labels, two-speaker hyphen format, numbers spelled out, US/UK spelling) is ALWAYS
  a script rule, even if it mentions seconds or frames. Only TIMING / DURATION /
  GAP / POSITIONING / FONT / FILE / DELIVERY / CREDIT rules go to subtitler_rules.

When in doubt, ask: "Does this change the WORDS or PUNCTUATION of the dialogue?" If YES
→ script_rules. If it is a TIMING / READING-SPEED / DURATION / GAP / ZERO-SUBTITLE rule
→ subtitler_rules (the operational engine applies it). If it is positioning/font/file/
delivery → subtitler_rules (recorded as a human checklist note).

HARD RULE: maximum characters per line, maximum number of lines, capitalisation/case,
spelling, profanity, ellipsis, acronyms, italics, sound/HOH removal, filler words,
speaker labels, number formatting, and US/UK spelling ALWAYS go to script_rules — never
to subtitler_rules.

Return a JSON object with two arrays of objects:

{{
    "script_rules": [
        {{ "rule": "Maximum 42 characters per line", "verbatim_quote": "no more than 42 characters on a single line" }}
    ],
    "subtitler_rules": [
        {{ "rule": "Frame gap must be 2 frames", "verbatim_quote": "ensure a 2-frame gap between subtitles" }}
    ]
}}

RULES FOR EXTRACTION:
- Extract EVERY distinct rule you can find — do not skip any.
- Classify using the capability lists above. Text/punctuation/format changes go to
  script_rules; timing/positioning/font/file/delivery go to subtitler_rules.
- Each item must be one complete, self-contained rule sentence.
- You MUST provide a 'verbatim_quote' for every rule — exact consecutive words copied
  directly from the text.
- If you cannot find a direct quote in the text for a rule, DO NOT include the rule.
  (This is strictly to prevent hallucination.)
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
        result_text = _re.sub(r"```(?:json)?\s*", "", result_text).strip().rstrip("`")
        
        parsed = None
        # Try direct parse first
        try:
            parsed = json.loads(result_text)
        except json.JSONDecodeError:
            # Try repairing truncated JSON
            try:
                repaired = _repair_truncated_json(result_text)
                parsed = json.loads(repaired)
            except Exception:
                pass
        
        if isinstance(parsed, dict):
            # Map object array back to string array, discarding hallucinated rules without quotes
            def _extract_valid_rules(rule_objs):
                valid = []
                for obj in (rule_objs or []):
                    if isinstance(obj, str): 
                        valid.append(obj)
                    elif isinstance(obj, dict):
                        rule = obj.get("rule", "")
                        quote = obj.get("verbatim_quote", "")
                        # Simple anti-hallucination validation: require a quote with at least 1 word
                        if rule and quote and len(quote.strip().split()) >= 1:
                            valid.append(rule)
                return valid

            return {
                "script_rules": _extract_valid_rules(parsed.get("script_rules", [])),
                "subtitler_rules": _extract_valid_rules(parsed.get("subtitler_rules", []))
            }

    except Exception as e:
        print(f"[RULES ERROR] LLM call failed: {e}")
    return {"script_rules": [], "subtitler_rules": []}


def _call_llm_for_metadata(client, model_name: str, platform_name: str, sample: str) -> dict:
    """
    Extract numeric/structural metadata from the guidelines document.
    Returns a dict with numeric fields.
    """
    prompt = f"""Read this subtitle guidelines document excerpt for "{platform_name}" and extract the metadata the SCRIPT CLEANER needs.

Return ONLY valid JSON (no comments, no markdown):
{{
  "name": "{platform_name}",
  "max_chars_per_line": 42,
  "max_lines": 2,
  "min_duration_seconds": 1.0,
  "max_duration_seconds": 7.0,
  "reading_speed_max_cps": 21,
  "file_format": "PAC",
  "two_speaker_format": "hyphen_no_space",
  "zero_subtitle_required": true,
  "remove_elements": ["stage_directions", "character_names", "hoh", "emt", "scene_descriptions", "fillers"],
  "italics": "song_lyrics_and_foreign_words",
  "profanity_handling": "replace_with_list_or_mask_asterisks",
  "summary": "One sentence summary of this platform's subtitle style"
}}

FIELD GUIDANCE:
- "remove_elements": list ONLY the element types the guidelines say to REMOVE from the
  dialogue text. Use these exact tokens when applicable:
  "hoh" (Hard-of-Hearing / sound descriptors like [MUSIC]), "emt" (same family),
  "stage_directions" (parenthetical actions/notes), "character_names" (speaker labels),
  "scene_descriptions", "fillers" (uh/hmm/er). Omit any not mentioned.
- "two_speaker_format": "hyphen_no_space" (-Word), "hyphen_with_space" (- Word), or "" if unspecified.
- "italics": describe what gets italics — e.g. "song_lyrics", "foreign_words",
  "narration_vo", "none" (platform forbids italics), or "all_common".
- "profanity_handling": "replace" (swap per word list), "asterisks" (mask as ****),
  "none", or "both".
- Numeric fields: characters per line, max lines, and reading-speed (CPS) limits that
  are stated as TEXT constraints on the subtitle. Leave timing/frame values out — those
  are subtitler tasks, not cleaner metadata.

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
    CHUNK_SIZE = 3000
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
        # Post-process: move any subtitler-operational rules that the 8B model
        # misclassified as script rules into the correct bucket.
        if isinstance(s_rules, list) and isinstance(m_rules, list):
            s_rules, m_rules = _filter_script_rules(s_rules, list(m_rules))
        print(f"[RULES] Chunk {i+1} yielded {len(s_rules)} script rules, {len(m_rules)} subtitler rules")

        if isinstance(s_rules, list): all_script_rules.extend(s_rules)
        if isinstance(m_rules, list): all_subtitler_rules.extend(m_rules)

    # ── Step 3: normalize + de-duplicate into clean rule sentences ─────────
    unique_script_rules = _normalize_rule_list(all_script_rules)
    unique_subtitler_rules = _normalize_rule_list(all_subtitler_rules)

    print(f"[RULES] Total unique script rules: {len(unique_script_rules)}, subtitler rules: {len(unique_subtitler_rules)}")

    if not unique_script_rules and not unique_subtitler_rules:
        # Fallback: return defaults so the platform is still saved
        return default

    # ── Step 4: extract numeric metadata from the first chunk ───────────────
    metadata = _call_llm_for_metadata(client, model_name, platform_name, chunks[0])

    # ── Step 5: merge ────────────────────────────────────────────────────────
    # Derive canonical script-cleaning rule phrases from the structured metadata
    # so the cleaner's phrase-matchers (auto_fix_subtitles / italic_formatter /
    # quality_checker) actually fire. The verbatim extracted rules already carry
    # the platform's own wording; these ensure the engine knobs are always set.
    derived_script = []
    italics = (metadata.get("italics") or "").lower()
    if "none" in italics:
        derived_script.append("No italics — plain text only")
    if "song" in italics:
        derived_script.append("Song lyrics in italics")
    if "foreign" in italics:
        derived_script.append("Foreign words in italics")
    if "narrat" in italics or "vo" in italics:
        derived_script.append("Narration / voice-over in italics")
    prof = (metadata.get("profanity_handling") or "").lower()
    if "asterisk" in prof:
        derived_script.append("Beeped profanity masked with asterisks (****)")
    elif "replace" in prof or "both" in prof:
        derived_script.append("Profanity replaced per platform profanity table")

    # Merge derived phrases into the script rules, de-duplicating (case-insensitive).
    merged_script = unique_script_rules[:]
    seen = {r.lower() for r in merged_script}
    for d in derived_script:
        if d.lower() not in seen:
            merged_script.append(d)
            seen.add(d.lower())

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
        "remove_elements":          metadata.get("remove_elements", []) or [],
        "italics":                  metadata.get("italics", ""),
        "profanity_handling":       metadata.get("profanity_handling", ""),
        "summary":                  metadata.get("summary", f"Custom platform: {platform_name}"),
        "rules":                    merged_script,
        "subtitler_rules":          unique_subtitler_rules,
    }
    return result
