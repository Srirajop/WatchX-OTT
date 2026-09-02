# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, '.')
from cleaner import _post_process_line

print("=== Real-world verification ===\n")
cases = [
    "<cHuckling exhale> Yeah... <exclaims>",
    "<laughs> <chuckles>",
    "Like Broadway, maybe. The legitimate stage.",
    "<moans>",
    "<cHuckling exhale> Yeah... <exclaims> <laughs>",
    "Meredith, hold on. Have you really thought this through?",
    "<i>None</i>.",
    "<i>Non</i>e.",
    "(laughs) No, seriously.",
    "Oh, <sighs> God.",
    "He said, <exclaims> what is this?",
]
for t in cases:
    out = _post_process_line(t)
    print(f"IN:  {t!r}")
    print(f"OUT: {out!r}")
    print()
