# J.A.R.V.I.S.

A personal AI assistant that knows who it works for, sounds like itself, and can
act on your computer. Built on free tools, one working feature at a time.

**Version 2.0.** Memory, personality and the agent core are in. Voice and web
research come next. [What works and how it was verified](docs/ROADMAP.md).

## What it does

- **Remembers you.** Tell it something once and it is kept: across
  conversations, across restarts. It also notices lasting things you mention
  and shows you what it learned, with Undo. A Memory screen lets you search,
  edit, pin, delete and export everything it knows.
- **Has a personality you can shape.** A composed, dry, British-butler voice by
  default. Adjust manner, humour and answer length, or just tell it ("shorter
  answers", "stop calling me sir") and it keeps that as a standing instruction.
- **Acts, and tells the truth about it.** It can open apps and web pages and
  check your computer's status. Each action appears in the conversation with
  its real outcome, and in an Activity log. You decide what runs freely and
  what must ask first.
- **Handles the free tier gracefully.** Several models in rotation, automatic
  fallback when one is rate-limited, and a status panel showing what you've
  used today.
- **Renders maths, code and tables** properly.

Not yet: voice, web search, files, reminders, phone access. JARVIS knows this
and says so if asked.

## Install (Windows)

You need **Git** and an internet connection.

1. In PowerShell:
   ```powershell
   cd $HOME
   git clone https://github.com/Fanaticmouse221/jarvis.git
   cd jarvis
   ```
   Keep the folder outside OneDrive; cloud sync can corrupt the database.
2. Double-click **`setup.bat`**. It installs [uv](https://docs.astral.sh/uv/)
   if needed, a private copy of Python 3.12 and the dependencies, runs the
   self-tests and puts a **JARVIS** shortcut on your desktop.
3. Double-click **JARVIS** on the desktop (or `start.bat`). A window opens.
4. The first screen asks for a free Groq key. Create one at
   [console.groq.com/keys](https://console.groq.com/keys) (no payment details),
   paste it in, and press Connect. JARVIS checks it and picks the models your
   account can use.

Already have 0.1? Double-click **`update.bat`**, then `setup.bat` once. Your
conversations and `.env` are kept and the database upgrades itself.

No key yet? Choose "try the scripted demo" on the first screen. It is not an
AI, but it lets you see the interface and the memory system working.

## First things to try

| Say | What should happen |
|---|---|
| "My name is … and I'm studying …" | A "Learned" note appears under the reply |
| "Remember that I prefer …" | A "Saved to memory" step |
| Close JARVIS, start it again, ask "What do you know about me?" | It tells you |
| "Open Spotify" (or any installed app) | The app opens; the step says whether that was confirmed |
| "From now on keep answers to two sentences" | Saved as a standing instruction and followed afterwards |
| "How's my computer doing?" | Real CPU, memory, disk and battery figures |

Then look at **Memory**, **Activity** and **Settings** in the left-hand rail.

## Free tier

| Provider | Free tier | Payment details | Uses your data to train | Role |
|---|---|---|---|---|
| **Groq** | Per model: 30 requests/min, 1,000/day, 8,000 tokens/min, 200,000 tokens/day | Not needed | No | Primary |
| Google Gemini | Low daily caps | Not needed | Yes, on the free tier | Optional fallback |
| OpenRouter | 50 requests/day on free models | Not needed | Varies | Optional fallback |
| Ollama | Unlimited, on your PC | None | Nothing leaves your PC | Optional; slow without a graphics card |

Limits change. Settings shows what Groq reports as remaining, and you can set
your own daily cap. Without payment details on your Groq account nothing can
be charged.

## Privacy

- Conversations, memories and the action log are stored only on your PC, in `data/jarvis.db`.
- Each message is sent to the model you've chosen, together with recent history
  and the memories relevant to it. That is how JARVIS uses what it knows.
- JARVIS refuses to store anything that looks like a password, key or card number.
- Only JARVIS's own window can talk to it; other web pages and other devices cannot.
- Your API key stays in `.env` on your PC.

## Troubleshooting

| Problem | Fix |
|---|---|
| `uv is not recognized` | Close the window and run `setup.bat` again. |
| "Groq rejected that key" | Copy the key again; make sure nothing is cut off. |
| A model shows "Not ready" or fails the test | It may have been retired. In Settings > Models, remove it and add another from the list. |
| "Rate limit reached. Resuming in N s." | Normal on the free tier. JARVIS waits or switches model by itself. |
| "Missing or invalid session token" | Reload the window. |
| The window didn't open | Go to <http://127.0.0.1:8000> in any browser. |
| Port 8000 in use | Set `JARVIS_PORT=8001` in `.env`. |
| "No installed app matches …" | Use the name as it appears in the Start menu; JARVIS suggests close matches. |

`check.bat` tests each model from the command line.

## For developers

```powershell
uv run pytest                 # 67 tests
uv run jarvis --help
uv run jarvis serve --port 8001 --no-browser
python tests/e2e/run_e2e.py   # full browser run (needs Playwright and Chrome)
```

```
jarvis/
├── jarvis/
│   ├── agent.py          the turn loop: context, model, tools, approvals
│   ├── persona.py        personality: the system prompt builder
│   ├── memory.py         long-term memory and background learning
│   ├── tools/            tool framework and tools (memory, computer)
│   ├── llm/              providers, fallback router, scripted test models
│   ├── storage.py        SQLite: conversations, memories, settings, logs, usage
│   ├── prefs.py          preferences changed in the app
│   ├── runtime.py        wiring; keys; diagnostics
│   ├── server.py         API routes and their guard
│   ├── cli.py            start-up, app window, `check`
│   └── web/              interface (plain HTML/CSS/JS, bundled libraries)
├── tests/                pytest suite, plus e2e/ (mock provider + browser run)
├── docs/                 assessment, architecture, decisions, roadmap
└── setup.bat  start.bat  update.bat  check.bat
```

- [Assessment of 1.0](docs/ASSESSMENT-1.0.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Decisions](docs/DECISIONS.md)
- [Roadmap and status](docs/ROADMAP.md)
- [Changelog](CHANGELOG.md)

Bundled front-end libraries and fonts are listed with their licences in
`jarvis/web/vendor/licenses/`.
