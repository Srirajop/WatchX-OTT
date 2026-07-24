# SubtitleAI V2 — Cleaning & Quality Check Tool

Built with: React + Python FastAPI + Groq (LLaMA 3.1 8B Instant) + MySQL

---

## What This Tool Does

### Tab 1 — Clean
- Upload ANY OTT script file (DOC, DOCX, PDF, SRT, VTT, XML, TTML, RTF, XLSX, CSV, TXT)
- Auto-detects file structure (table, paragraph, CCSL, SRT, etc.)
- AI removes: character names, stage directions, slang notes, scene descriptions, HOH/EMT elements
- Applies OTT platform-specific rules (char limits, reading speed, etc.)
- Flags lines that need human review
- Export as SRT or TXT

### Tab 2 — Quality Check
- Checks cleaned file against real OTT platform rules before delivery
- Catches: file naming errors, missing zero subtitle, line too long, reading speed, profanity not replaced, spacing defects, HOH/EMT elements, duration issues
- Shows every defect with severity (critical/error/warning), line number, and fix suggestion
- Green light = ready to send to OTT. Red = fix first.

### Tab 3 — Platforms
- All 8 real platforms loaded from OTT Clients Protocol Excel
- Add any new platform by uploading their guidelines document
- AI reads guidelines and extracts rules automatically

### Subtitle Edit tab — Auto-Translate (multi-provider AI)
The Subtitle Edit tab has an Auto-Translate window that mirrors Subtitle Edit's
multi-engine translation. A subtitler picks a provider, pastes their own API
key (plus optional model + custom endpoint), and every line is translated into
the target language. The key is stored only in the browser (localStorage) and is
sent straight to the engine you chose.

Supported providers (just like Subtitle Edit):
- **Google Translate** — free, no key needed (default)
- **ChatGPT / OpenAI**, **Claude (Anthropic)**, **Google Gemini**
- **DeepL**, **DeepSeek**, **Groq**, **Mistral**, **OpenRouter**, **Perplexity**
- **Ollama** (local), **LibreTranslate** (local/hosted), **Azure Translator**
- **OpenAI-Compatible API** — point at any `/v1/chat/completions` endpoint
  (vLLM, LM Studio, Together, xAI, …)

How to use:
1. Open the Subtitle Edit tab → 🌐 Auto-Translate.
2. Pick the engine, paste your API key (for keyed engines), choose model/endpoint.
3. Pick Source (optional, leave blank = auto-detect) and Target language.
4. Translate. A live “translating N / Total” popup shows progress; you can
   Stop & Apply or Stop & Revert mid-flight. Speaker labels and `<i>`/`<b>`
   tags are preserved.

Server-side key fallback: if a subtitler leaves the key blank, the backend will
use a matching env var (e.g. `OPENAI_API_KEY`) if you set one in `.env`.

---

## Built-in Platforms (from your OTT Clients Protocol Excel)

| Platform | Max Chars | Max Duration | File Format | Special |
|---|---|---|---|---|
| Discovery Max V2 | 37 | 7s | PAC | 15 CPS target, 21 CPS max |
| Discovery Scripps (SNI) | 36 | 6s | PAC | Multiple sub-channels |
| Nickelodeon V10 | 42 | 7s | PAC | No italics for songs |
| Disney V38 | 42 | 7s | PAC | Detailed profanity rules |
| TVB V11 | 44 | 15s | PAC | Hyphen WITH space |
| DMAX | 37 | 7s | PAC | Remove HOH/EMT |
| Guide Discovery | 37 | 7s | PAC | EHD_123456E_ENG.PAC naming |
| Vubiquity V2 | 50 | 7s | PAC | DVB style |

---

## Setup Instructions

### Requirements
- Python 3.10+
- Node.js 18+
- MySQL 8.0+

### Step 1 — Backend

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`:
```
GROQ_API_KEY=your_groq_api_key_here
DB_HOST=localhost
DB_PORT=3306
DB_NAME=subtitleai_v2
DB_USER=root
DB_PASSWORD=your_mysql_password
FRONTEND_URL=http://localhost:5173
```

Get FREE Groq API key: https://console.groq.com

Start backend:
```bash
uvicorn main:app --reload --port 8000
```

Database and tables are created automatically on first run.

### Step 2 — Frontend

```bash
cd frontend
npm install
npm run dev
```

Open: http://localhost:5173

---

## How The 5 Script Formats Are Handled

| Format | Example Files | How AI Cleans It |
|---|---|---|
| Already cleaned | Help me.docx | Fix spelling, punctuation only |
| Paragraph with speaker | Everybody Loves Raymond, CSI | Remove speaker names, scene headings |
| Table with timecodes | FBoy Island, Tiny Toons | Extract timecode + dialogue columns only |
| Paragraph with timecodes | EVIL script, SRT file | Extract timecode + dialogue, remove character |
| CCSL double dialogue | Juno, Late Night with the Devil | Find clean dialogue column, extract timecodes |

---

## Quality Checks Performed

| Check | What It Catches |
|---|---|
| File naming | Must match EHD_123456E_ENG.PAC for Discovery |
| Zero subtitle | Missing or incorrectly formatted first entry |
| Line too long | Exceeds platform char limit |
| Too many lines | More than 2 lines per subtitle |
| Duration too short | Below platform minimum |
| Duration too long | Exceeds platform maximum |
| Reading speed | Exceeds platform CPS limit |
| Profanity | Words that must be replaced (fxxx, cxxx etc.) |
| HOH/EMT elements | Accessibility markers that must be removed |
| Double spaces | Extra spaces anywhere |
| Space before punctuation | Space before comma, period etc. |
| Double punctuation | !! or ?? |
| Starts with lowercase | Line doesn't begin with capital |
| Trailing spaces | Space at start or end of line |
| ALL CAPS overuse | Multiple all-caps words |

---

## Project Structure

```
subtitleai-v2/
  README.md
  backend/
    main.py              — FastAPI routes
    cleaner.py           — Groq + LLaMA 3.1 8B cleaning
    file_reader.py       — Smart reader for all formats
    quality_checker.py   — OTT defect checker
    platform_rules.py    — All 8 real platform rules
    editor.py            — Subtitle import/export/sync + translate dispatch
    translate_engines.py — Multi-provider AI translation engines
    database.py          — MySQL setup
    requirements.txt
    .env.example
  frontend/
    src/App.jsx          — Full React UI (3 tabs)
    src/main.jsx
    index.html
    package.json
    vite.config.js
```

---

## Agent Setup Instructions

Paste this to your AI coding agent:

> "Set up and run this subtitle cleaning web tool called subtitleai-v2.
>
> Backend: Go into the backend folder. Run `pip install -r requirements.txt`.
> Copy `.env.example` to `.env`. Fill in GROQ_API_KEY (free from console.groq.com) and MySQL password.
> Run `uvicorn main:app --reload --port 8000`.
> The database 'subtitleai_v2' and all tables are created automatically.
>
> Frontend: Go into the frontend folder. Run `npm install` then `npm run dev`.
>
> Open http://localhost:5173.
>
> Test: Upload the FBoy Island DOCX file in the Clean tab with Discovery Max selected.
> Then click Quality Check to see any defects."
