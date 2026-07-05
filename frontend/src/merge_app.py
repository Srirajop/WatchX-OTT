import re

with open(r'D:\Downloads\OTTWatchX\subtitleai-v2\subtitleai-v2\frontend\src\App_ours.jsx', 'r', encoding='utf-8') as f:
    ours = f.read()

with open(r'D:\Downloads\OTTWatchX\subtitleai-v2\subtitleai-v2\frontend\src\App.jsx', 'r', encoding='utf-8') as f:
    claudes = f.read()

# 1. State hooks
states = re.search(r'(  // Transcribe tab.*?)(?=  // Track Changes)', ours, re.DOTALL)
if states:
    claudes = claudes.replace('  // Track Changes (on-screen view, before PDF download)', states.group(1) + '  // Track Changes (on-screen view, before PDF download)')

# 2 & 3. Functions
load_movies = re.search(r'(  async function loadMovies\(\).*?setMovieErr\(.*?failed to add movie\.\'\)\n    \}\n  \})', ours, re.DOTALL)
if load_movies:
    claudes = claudes.replace('  // ── GUIDELINES SEARCH ENGINE ────────────────────────────────────', load_movies.group(1) + '\n\n  // ── GUIDELINES SEARCH ENGINE ────────────────────────────────────')
    
# also we need to call loadMovies in useEffect
claudes = claudes.replace('loadPlatforms(); loadGuidelineFilters();', 'loadPlatforms(); loadGuidelineFilters(); loadMovies();')

transcribe_funcs = re.search(r'(  // ── TRANSCRIBE ──────────────────────────────────────────────────.*?)(?=  // ── TIMECODE ADJUSTER)', ours, re.DOTALL)
if transcribe_funcs:
    claudes = claudes.replace('  // ── TIMECODE ADJUSTER (Case 3) ──────────────────────────────────', transcribe_funcs.group(1) + '  // ── TIMECODE ADJUSTER (Case 3) ──────────────────────────────────')

# 4. Tabs
tabs_str = r"[['clean','🧹 Clean'],['adjust','⏱️ Adjust TC'],['quality','✅ Quality Check'],['platforms','⚙️ Platforms'],['guidelines','📚 Guidelines']]"
new_tabs_str = r"[['clean','🧹 Clean'],['transcribe','🎙️ Transcribe'],['adjust','⏱️ Adjust TC'],['quality','✅ Quality Check'],['platforms','⚙️ Platforms'],['movie_hub','🌐 Movie Hub'],['guidelines','📚 Guidelines']]"
claudes = claudes.replace(tabs_str, new_tabs_str)

# 5 & 6. JSX blocks
transcribe_jsx = re.search(r'(        \{\/\* ══ TRANSCRIBE TAB ══ \*\/.*?)(?=        \{\/\* ══ ADJUST TIMECODES TAB ══ \*\/)', ours, re.DOTALL)
movie_hub_jsx = re.search(r'(      \{\/\* ══ MOVIE HUB TAB ══ \*\/.*?)(?=      \{\/\* ══ TRACK CHANGES MODAL)', ours, re.DOTALL)

if transcribe_jsx:
    claudes = claudes.replace('        {/* ══ ADJUST TIMECODES TAB ══ */}', transcribe_jsx.group(1) + '        {/* ══ ADJUST TIMECODES TAB ══ */}')

if movie_hub_jsx:
    claudes = claudes.replace('      {/* ══ TRACK CHANGES MODAL', movie_hub_jsx.group(1) + '      {/* ══ TRACK CHANGES MODAL')

with open(r'D:\Downloads\OTTWatchX\subtitleai-v2\subtitleai-v2\frontend\src\App.jsx', 'w', encoding='utf-8') as f:
    f.write(claudes)
print('Merged App.jsx')
