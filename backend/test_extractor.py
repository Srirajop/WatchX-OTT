from extractor import read_file, pre_extract_dialogue
from platform_rules import get_platform
import traceback

filename = r"d:\Downloads\OTTWatchX\T13.22212 - Only Time Will Tell.docx_cleaned.pdf"

try:
    with open(filename, "rb") as f:
        file_bytes = f.read()

    file_data = read_file(file_bytes, filename)
    raw_text = file_data["raw_text"]
    structure = file_data["structure"]
    
    platform_dict = get_platform("generic")
    pre_extracted = pre_extract_dialogue(raw_text, structure, file_bytes, filename, platform_dict)
    print(f"Success! Extracted {len(pre_extracted)} lines")
except Exception as e:
    traceback.print_exc()
