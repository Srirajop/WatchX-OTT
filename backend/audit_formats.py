"""Quick audit: test extraction on key script formats (no heavy OCR)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from file_reader import read_file
from timecoded_subtitles import parse_timecoded_subtitles
from extractor import pre_extract_dialogue

scripts = [
    ("EVIL SRT",           r"D:\Downloads\OTTWatchX\EVIL_0405_FINAL_TC_IYUNO SDI.srt"),
    ("T13 docx",           r"D:\Downloads\OTTWatchX\T13.22212 - Only Time Will Tell.docx"),
    ("FoodFactory docx",   r"D:\Downloads\OTTWatchX\FoodFactoryS2_EpTheNamesBoondi_NGCP_YA90027775_1159556_111620_BMSub (1).docx"),
    ("CAR SOS docx",       r"D:\Downloads\OTTWatchX\CAR SOS 2023 COMPS - UNSEEN - FINAL SCRIPT RD503340.docx"),
    ("COYOTE docx",        r"D:\Downloads\OTTWatchX\scripts_unzipped\All Possible Current scripts\ALL Script\COYOTE_102_TV_As-Broadcast Dialogue List (2).docx"),
    ("FBoyIsland docx",    r"D:\Downloads\OTTWatchX\scripts_unzipped\All Possible Current scripts\ALL Script\FBoyIsland_S3EP06_InternationalScript (1).docx"),
    ("Tiny Toons PDF",     r"D:\Downloads\OTTWatchX\scripts_unzipped\All Possible Current scripts\ALL Script\Tiny Toons - Eps 19- Nightmare On Toon Street Part One-A14.15746.pdf"),
    ("EVIL PDF",           r"D:\Downloads\OTTWatchX\scripts_unzipped\All Possible Current scripts\ALL Script\EVIL_0405_FINAL_TC_IYUNO SDI.pdf"),
    ("ELR PDF",            r"D:\Downloads\OTTWatchX\scripts_unzipped\All Possible Current scripts\ALL Script\Everybody_Loves_Raymond_S8_E10_JAZZ_RECORDS_RD343797.pdf"),
    ("Juno doc",           r"D:\Downloads\OTTWatchX\scripts_unzipped\All Possible Current scripts\ALL Script\Juno - CCSL - Reel 1AB.doc"),
    ("RD343797 xml",       r"D:\Downloads\OTTWatchX\scripts_unzipped\All Possible Current scripts\ALL Script\RD343797-TOM61_SU_ENG.xml"),
    ("1067692 docx",       r"D:\Downloads\OTTWatchX\scripts_unzipped\All Possible Current scripts\ALL Script\1067692.docx"),
    ("Presto rtf",         r"D:\Downloads\OTTWatchX\Presto-CDSL-R4.rtf"),
]

print(f"{'Name':<22} {'Fmt':<6} {'Structure':<26} {'TC parsed':>9} {'Extracted':>9} {'Raw lines':>9}")
print("-" * 95)

for name, path in scripts:
    try:
        data = open(path, "rb").read()
        res = read_file(data, os.path.basename(path))
        subs_tc = parse_timecoded_subtitles(res["raw_text"])
        extracted = pre_extract_dialogue(res["raw_text"], res["structure"], data, os.path.basename(path), {})
        print(f"{name:<22} {res['format']:<6} {res['structure']:<26} {len(subs_tc):>9} {len(extracted):>9} {len(res['raw_text'].splitlines()):>9}")
    except Exception as e:
        print(f"{name:<22} ERROR: {e}")
