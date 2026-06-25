import sys

with open(r"d:\Downloads\OTTWatchX\claude_fixes\WatchX-OTT-main\backend\main.py", "r", encoding="utf-8") as f:
    claude_main = f.read()

with open(r"d:\Downloads\OTTWatchX\subtitleai-v2\subtitleai-v2\backend\main.py", "r", encoding="utf-8") as f:
    my_main = f.read()

# Extract /track-changes endpoint from Claude's main.py
import re
match = re.search(r'(@app\.post\("/track-changes"\).*?)(?=@app\.post\("/export/track-changes-pdf"\))', claude_main, re.DOTALL)
if match:
    track_changes_code = match.group(1)
    
    # Insert it before /export/track-changes-pdf in my_main
    my_main = my_main.replace('@app.post("/export/track-changes-pdf")', track_changes_code + '\n@app.post("/export/track-changes-pdf")')
    
    # Also update my /export/track-changes-pdf to use deduce_change_rules from quality_checker
    # Actually, it's easier to just copy Claude's /export/track-changes-pdf completely, EXCEPT I need to be careful if I made changes to it recently.
    # I will just write the merged file.
    
    with open(r"d:\Downloads\OTTWatchX\subtitleai-v2\subtitleai-v2\backend\main_merged.py", "w", encoding="utf-8") as f:
        f.write(my_main)
    print("Merged successfully!")
else:
    print("Could not extract track-changes code.")
