import os
from dotenv import load_dotenv
load_dotenv('backend/.env')

from backend.cleaner import extract_platform_rules_with_ai

dummy_guidelines = """
Subtitle Guidelines for Discovery:
1. Max 42 characters per line.
2. Max 2 lines.
3. Remove [MUSIC] and other sound tags.
4. Ensure a minimum of 2 frames between subtitles.
5. All song lyrics must be in italics.
"""

print("Running test...")
res = extract_platform_rules_with_ai(dummy_guidelines, "Discovery Test")
print("Result:", res)
