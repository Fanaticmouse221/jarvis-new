# J.A.R.V.I.S.

**Just A Rather Very Intelligent System**: a personal AI assistant built on free tools, growing one working feature at a time.

**Status: Phase 1 (text chat foundation) is complete.** Voice is next. See the [roadmap](docs/ROADMAP.md).

## What works now

- Chat with JARVIS in your browser, with replies that stream in as they're written
- A consistent JARVIS personality: composed, precise, occasionally dry
- Formatted replies: headings, lists, tables and code blocks with copy buttons
- Conversations saved on your PC and kept across restarts; rename and delete them
- Free cloud AI models with **automatic fallback** if one is busy or rate-limited
- Layout that works on narrow windows and phones (this computer only, for now)
- An offline demo mode for trying the interface without an API key

## Quick start (Windows)

You need **Git** and an internet connection. Everything else is installed by `setup.bat`.

1. **Get the code.** Open PowerShell and run:
   ```powershell
   cd $HOME
   git clone https://github.com/Fanaticmouse221/jarvis.git
   cd jarvis
   ```
   Keep it outside OneDrive, because cloud sync can corrupt the conversation database.
2. **Run `setup.bat`** (double-click it in File Explorer). It installs
   [uv](https://docs.astral.sh/uv/) if needed, then Python 3.12 and the dependencies
   into a private `.venv` folder, creates your `.env` file and runs the self-tests.
3. **Get a free Groq API key** at [console.groq.com/keys](https://console.groq.com/keys).
   No payment method is required. Don't add one, so nothing can ever be charged.
4. **Open `.env` in Notepad** and paste the key after `GROQ_API_KEY=`. Save.
5. **Run `check.bat`.** Each model should report `OK`.
6. **Run `start.bat`.** Your browser opens at <http://127.0.0.1:8000>. Close the black
   window to shut JARVIS down.

To try the interface without any key, set `JARVIS_MODELS=fake:demo` in `.env`.

To update later: `git pull`, then run `setup.bat` again.

## Configuration

All settings live in `.env` (see [`.env.example`](.env.example) for every option, with explanations).

| Setting | Default | What it does |
|---|---|---|
| `GROQ_API_KEY` | (empty) | Key for the primary model provider |
| `JARVIS_MODELS` | `groq:openai/gpt-oss-120b,groq:llama-3.1-8b-instant` | Models in priority order; later ones are fallbacks |
| `JARVIS_REASONING_EFFORT` | `low` | How long gpt-oss models think: `low`, `medium` or `high` |
| `JARVIS_USER_NAME` / `JARVIS_USER_TITLE` | (empty) / `sir` | How JARVIS addresses you |
| `JARVIS_PORT` | `8000` | Web interface port |
| `JARVIS_HOST` | `127.0.0.1` | Keep this: only your PC can connect |

### Free model options (checked November 2026)

| Provider | Free tier | Card needed | Trains on your data | Role in JARVIS |
|---|---|---|---|---|
| **Groq** | Rate-limited per model; e.g. gpt-oss-120b: 30 requests/min, 1,000/day | No | No | **Primary** |
| Google Gemini | Flash models, low daily caps | No | **Yes** (free tier) | Optional fallback |
| OpenRouter | `:free` models, 50 requests/day | No | Varies by model | Optional fallback |
| Ollama (local) | Unlimited, runs on your PC | No | Nothing leaves your PC | Optional, offline |

Free-tier limits change often. Your provider's dashboard is the authority.
Groq's and Google's terms require account holders to be 18 or older.

**Running models locally.** On a laptop CPU with integrated graphics, local models
work but are slow (a few words per second) and noticeably less capable than the
cloud models above. They're best kept as an offline backup.

## Privacy

- Conversations are stored **only on your PC**, in `data/jarvis.db`.
- Each message (with recent history) is sent to whichever cloud model answers it.
- Groq does not train on API data. You can also enable *Zero Data Retention* in
  Groq's console under Data Controls.
- Google's free Gemini tier may use your prompts to improve its products. Avoid
  sending personal information through it.
- JARVIS only listens on `127.0.0.1`, so other devices on your network can't reach it.

## Troubleshooting

| Problem | Fix |
|---|---|
| `uv is not recognized` | Close the window and run `setup.bat` again (a fresh window picks up the new PATH). |
| `check` says HTTP 401 | The API key is wrong or has a stray space. Re-copy it into `.env`. |
| `check` says HTTP 404 | The model has been retired. `check` lists the current models; update `JARVIS_MODELS`. |
| HTTP 429 / rate limit | Free-tier limit reached. Wait a minute, or add a fallback model. |
| HTTP 413 / request too large | Start a new conversation, or lower `JARVIS_MAX_CONTEXT_CHARS`. |
| Status pill says "Offline" | The server window was closed. Run `start.bat`. |
| Port 8000 already in use | Set `JARVIS_PORT=8001` in `.env`. |

## Development

```powershell
uv run pytest           # run the test suite
uv run jarvis --help    # command-line options
uv run jarvis serve --port 8001 --no-browser
```

```
jarvis/
├── jarvis/
│   ├── cli.py            command line: serve, check
│   ├── config.py         settings from .env
│   ├── persona.py        JARVIS's personality (system prompt)
│   ├── chat.py           conversation orchestration
│   ├── storage.py        SQLite persistence with migrations
│   ├── server.py         FastAPI: REST + streaming API, serves the web UI
│   ├── llm/              model providers, presets and fallback router
│   └── web/              browser interface (HTML/CSS/JS, no build step)
├── tests/                pytest suite
├── docs/                 architecture, decisions, roadmap
├── setup.bat / start.bat / check.bat
└── .env.example
```

- [Architecture](docs/ARCHITECTURE.md): how the pieces fit and where future phases plug in
- [Decisions](docs/DECISIONS.md): why each technology was chosen
- [Roadmap](docs/ROADMAP.md): phases, progress and what's next
- [Changelog](CHANGELOG.md)
