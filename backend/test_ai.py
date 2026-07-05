import os, re
from dotenv import load_dotenv
load_dotenv()

def extract_platform_rules_with_ai(guidelines_text: str, platform_name: str) -> dict:
    from cleaner import _get_client_and_model
    import json
    client, model_name, _ = _get_client_and_model()

    prompt = f"""Read this subtitle guidelines document for "{platform_name}" and extract EVERY key formatting, grammar, punctuation, profanity, and timing rule into an exhaustive list. 
Do NOT just extract 2 or 3 rules. You MUST extract EVERY distinct instruction you can find in the document.

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
  "rules": ["Rule 1: ...", "Rule 2: ...", "Rule 3: ...", "Rule 4: ...", "Rule 5: ...", "(... include ALL rules found in the document ...)"],
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
        print('RAW AI RESPONSE:')
        print(result_text)
        cleaned = re.sub(r"```(?:json)?\s*", "", result_text).strip()
        match = re.search(r'\{.*\}', cleaned, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        print(f"[WARN] Platform rule extraction failed: {e}")

    return {'rules': ['FALLBACK']}

if __name__ == "__main__":
    guidelines = "1. Must be exactly 40 chars.\\n2. Italics for VO.\\n3. Spell out numbers 1-9.\\n4. No bold ever.\\n" * 10
    res = extract_platform_rules_with_ai(guidelines, 'Test Platform')
    print('Extracted Rules:', res.get('rules'))
