import io
import os
from file_reader import read_file
from timecoded_subtitles import parse_timecoded_subtitles

files = [
    ("EVIL SRT", r"D:\Downloads\OTTWatchX\EVIL_0405_FINAL_TC_IYUNO SDI.srt", "srt"),
    ("T13 docx", r"D:\Downloads\OTTWatchX\T13.22212 - Only Time Will Tell.docx", "docx"),
    ("FoodFactory docx", r"D:\Downloads\OTTWatchX\FoodFactoryS2_EpTheNamesBoondi_NGCP_YA90027775_1159556_111620_BMSub (1).docx", "docx"),
    ("Presto doc", r"D:\Downloads\OTTWatchX\Presto-CDSL-R4 (1) (1).doc", "doc"),
    ("Presto rtf", r"D:\Downloads\OTTWatchX\Presto-CDSL-R4.rtf", "rtf"),
    ("Testing pmw", r"D:\Downloads\OTTWatchX\TestingSubtitle.pmw", "pmw"),
    ("CAR SOS docx", r"D:\Downloads\OTTWatchX\CAR SOS 2023 COMPS - UNSEEN - FINAL SCRIPT RD503340.docx", "docx"),
]

for name, path, ext in files:
    try:
        data = open(path, "rb").read()
        res = read_file(data, os.path.basename(path))
        subs = parse_timecoded_subtitles(res["raw_text"])
        print("%-16s fmt=%-6s struct=%-22s parsed=%d" % (name, res["format"], res["structure"], len(subs)))
    except Exception as e:
        print("%-16s ERROR: %s" % (name, e))
