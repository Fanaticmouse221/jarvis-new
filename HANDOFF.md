# JARVIS handoff: read this first

This file lets any AI assistant (Claude, ChatGPT/Codex, Gemini, Cursor…) or person
pick up JARVIS exactly where the last session stopped. It is kept current: whoever
works on the project updates it, and `docs/WORKLOG.md`, before every commit.

**Last updated:** 10 November 2026, 11:00 AM (Brisbane) by ChatGPT/Codex.

## How to hand this to another AI (Jack's steps)

The repository is **private**, so another AI can't open it from the link alone.

1. Get the latest copy onto your PC: double-click `update.bat` in the `jarvis` folder.
2. Give the AI the code, either way:
   - **Easiest:** right-click the `jarvis` folder → *Compress to ZIP file* and upload
     the zip. (The zip leaves out nothing secret you need to worry about except
     `.env`, which holds your Groq key: delete `.env` from the zip, or tell the AI to ignore it.)
   - **Or:** connect your GitHub account inside that AI (ChatGPT's Codex and
     similar tools can then read and change the repo directly).
3. Paste this as your first message:

> You are taking over development of my project JARVIS, a personal AI assistant
> (repo: github.com/Fanaticmouse221/jarvis, private). Read `HANDOFF.md` first,
> then `AGENTS.md`, `docs/ARCHITECTURE.md`, `docs/DECISIONS.md` and
> `docs/ROADMAP.md`. Continue from the "What to do next" section of HANDOFF.md.
> Keep all tests passing. Before you stop, follow "Handing back" in HANDOFF.md
> so the next assistant can continue. I'm an AI-assisted developer, not a
> programmer: give me complete files and exact steps, ask one question at a
> time, and never claim something works unless you tested it.

## Handing back (for whichever AI is working: do this before you stop)

The next assistant, which may be Claude again, knows only what is in the repo.

1. Update this file: "Last updated", "Current state", tick finished boxes, and
   write under "What to do next" exactly where you stopped (file, function,
   what is half-done, what you were about to try).
2. Add an entry at the top of `docs/WORKLOG.md`: what changed, what you verified
   and how, what is unverified, what comes next. Sign it with your name
   (ChatGPT, Claude, Gemini…).
3. Run `uv run pytest -q`. If something fails and you can't fix it, say so in
   both files rather than leaving it for the next assistant to discover.
4. Get the work onto GitHub:
   - **If you can push:** commit to a branch, push, open a pull request for Jack to merge.
   - **If you can't** (you only had a zip): give Jack every changed or new file
     in full, with its path. Jack copies them into his `jarvis` folder and
     double-clicks **`save-work.bat`**, which commits everything and pushes it.
5. Tell Jack in plain words what you finished, what to test, and what is left.

**Jack, to continue in Claude afterwards:** open the Jarvis project in Claude and
say "Read HANDOFF.md and docs/WORKLOG.md in the repo and carry on." Claude reads
the repository from GitHub, so make sure the other AI's work was pushed (step 4).

## The project in one minute

- **What:** JARVIS is Jack's personal AI assistant (Iron Man style): long-term
  memory, a consistent personality, real tools that act on his PC. Free tools first.
- **Owner:** Jack (GitHub `Fanaticmouse221`), a student in Brisbane, Australia.
  He directs and tests; the AI designs and writes the code.
- **Runs on:** his Windows 11 laptop (Ryzen 5 5625U, integrated graphics, 16 GB
  RAM, about 26 GB free disk). No GPU, so models are cloud-hosted.
- **Stack:** Python 3.10+ (uv runs 3.12), FastAPI, SQLite, plain JavaScript with
  no build step, Server-Sent Events. One process. No agent framework.
- **Model:** Groq free tier, `openai/gpt-oss-120b` then `openai/gpt-oss-20b`
  (each 30 requests/min, 1,000/day, **8,000 tokens/min**, 200,000 tokens/day).
  Any OpenAI-compatible provider works; fallback down the list is automatic.
- **What matters most (Jack's words):** memory and personality are the product.

## Rules that must not be broken (full list in `AGENTS.md`)

1. **Free first.** Never add anything that could cost money without Jack's explicit
   yes. Check current pricing and limits before recommending a service.
2. **Never fake a capability.** Tools do the real thing and report the real outcome.
3. **Status claims need evidence.** "Tested and working" means automated tests plus
   a browser run. Anything only checked against a mock, or Windows-only, is
   "built, needs a real-world check".
4. **Ask before** major architecture changes, sensitive permissions, destructive actions.
5. **Never commit secrets.** Keys live only in `.env` (git-ignored).
6. British/Australian spelling. Times shown to Jack in 12-hour format (6:52 PM).
7. Keep prompts, tool descriptions and tool results small: Groq's 8,000
   tokens/min counts the prompt plus the reserved output (2,048).

## Current state

| | |
|---|---|
| Released | **v2.0.0** on `main` (PR #1 merged 10 Nov 2026) |
| Confirmed on Jack's PC | `setup.bat` ran, JARVIS started and replied; Jack: "that works good". He has not yet reported on memory after a restart, app opening, or tone. |
| Working branch | **`codex/jarvis-2.1-reach`**, from current `main` after the handoff branch was merged. |
| On that branch so far | Items 1–2 implemented: shared plumbing and Telegram phone access, protected endpoints and Phone settings. More tools and reminders are next. Draft PR #4. |
| Tests | Before Jack asked to stop testing: 175 tests passed in the working tree; a 51-check browser run completed (latest phone screenshots uninspected). Later fixes and integration changes are unverified. |

What exists in 2.0 (all in `docs/ROADMAP.md` with evidence): streaming chat,
long-term memory (told + learned automatically, survives restart, management
screen), personality with dials, agent loop with tools (`remember`, `recall`,
`forget`, `search_conversations`, `open_app`, `open_url`, `get_system_info`),
permissions and approvals, action log, rate-limit fallback, first-run key entry,
local API protection.

## What Jack has asked for (10 Nov 2026, in priority order)

1. **This handoff system**, so work can continue in another AI when one runs out of usage. *(done in this commit)*
2. **Message JARVIS from his phone.** He chose a **Telegram bot** over Tailscale or Wi-Fi-only.
3. **"It needs to be able to do more things."** More tools/abilities.
4. **Keep developing overall**: carry on down the roadmap (voice next).

## What to do next: version 2.1 "Reach"

Build in this order. Commit and push after each numbered item with tests passing,
ticking the box here. Design notes are decisions already made; follow them unless
you find a real problem, and record any change in `docs/DECISIONS.md`.

### [x] 1. Plumbing (small, needed by everything below)
- `storage.py`: migration v3. Add `conversations.source TEXT NOT NULL DEFAULT 'app'`
  ('app' or 'telegram') and a `reminders` table (id, text, due_at UTC ISO, repeat
  none/daily/weekdays/weekly, status pending/sent/cancelled, conversation_id,
  created_at, sent_at).
- `tools/base.py`: let a tool compute risk per call (e.g. optional
  `risk_for(args, ctx) -> str`) so overwriting a file is "sensitive" but creating
  one is "act". Add `channel` ("app"/"telegram") to `ToolContext`.
- `agent.py`: `run_turn(conversation, prefer=None, channel="app")`; pass channel
  to `build_system_prompt`.
- `persona.py`: build the "You cannot yet…" list from which tools are enabled
  (today `MISSING_ALWAYS` is a fixed string that says JARVIS can't browse, read
  files or set reminders; it must stop saying so once those tools exist). When
  channel is telegram, add one context line: the reply goes to a phone chat, so
  keep it short, plain text, no tables or LaTeX.
- `runtime.py`/`server.py`: a FastAPI lifespan that starts and stops background
  tasks (Telegram poller, reminder scheduler). `TestClient` used without `with`
  doesn't run lifespan, which keeps existing tests unaffected.

### [x] 2. Telegram phone link (Jack's top request)
- New `jarvis/telegram.py`. Plain `httpx`, no bot library. **Long polling**
  (`getUpdates`, timeout 25 s, `allowed_updates=["message","callback_query"]`):
  outbound requests only, so no port is opened and nothing is exposed to the internet.
- Token from @BotFather, entered in Settings, verified with `getMe`, saved to
  `.env` as `TELEGRAM_BOT_TOKEN` (same pattern as `config.save_api_key`). UI shows
  only the last 4 characters. API base overridable with `JARVIS_TELEGRAM_API` for tests.
- **Locked to Jack:** Settings shows a 6-digit pairing code; the first private
  chat that sends it becomes the owner (chat id stored in the `settings` table).
  Limit wrong guesses (5 per chat; rotate the code after 10). Every other chat is
  ignored silently. Private chats only.
- Owner messages run the **same agent** (same memory, personality, tools) in a
  conversation with `source='telegram'`; it shows in the PC sidebar with a phone
  icon. `/new` starts a fresh conversation (also automatic after 8 idle hours),
  `/stop` cancels the running reply, `/help`, `/start`.
- Process messages one at a time through a queue, but handle button presses and
  `/stop` straight from the poll loop (a turn waiting for approval must not block
  the approval).
- **Approvals:** on an `approval_required` event send a message with inline
  buttons Allow / Don't allow; on the `callback_query` call
  `runtime.approvals.resolve(id, approve)`, then edit the message to show the outcome.
- Replies: send the `typing` chat action every 4 s while working; send the final
  text when done. Convert Markdown to Telegram's HTML subset (b, i, code, pre, a;
  escape everything else); if Telegram rejects the HTML (400), resend as plain
  text. Split at paragraph breaks under 4,096 characters.
- Voice notes, photos, files: reply honestly that they aren't supported yet.
- Errors: 401 → "token rejected" and stop; 409 → "another program is using this
  bot token"; network errors → back off 2 s up to 60 s.
- API: `GET /api/telegram` (state, bot username, pairing code if unlinked, last
  error), `POST /api/telegram/token`, `POST /api/telegram/unlink`,
  `POST /api/telegram/test`, `DELETE /api/telegram`.
- Settings: a "Phone" section with numbered steps (install Telegram → message
  @BotFather `/newbot` → paste token → open the bot and send the code), status,
  and the privacy note below.
- **Privacy note to show Jack:** messages sent through Telegram pass through
  Telegram's servers (bot chats are not end-to-end encrypted). The PC must be on
  with JARVIS running.
- Tests: a fake Telegram API (httpx `MockTransport` for unit tests; a small
  FastAPI mock like `tests/e2e/mock_openai.py` for the browser run) covering
  pairing, wrong codes, strangers ignored, a full message → reply, an approval
  via buttons, `/new`, HTML fallback, long-message splitting.

### [ ] 3. New tools (each in `jarvis/tools/`, with a risk level and tests)
| Tool | Risk | Notes |
|---|---|---|
| `web_search(query)` | read, **untrusted output** | Use the `ddgs` package (keyless metasearch, MIT, v9.16 Oct 2026). Return top 5: title, link, snippet (≤ ~900 chars total). |
| `read_page(url, focus?)` | read, **untrusted output** | `httpx` GET, own HTML-to-text (stdlib `html.parser`), ≤ ~2,800 chars, optional `focus` keywords to pick the relevant paragraphs. **Block private, loopback and link-local addresses on every redirect hop** (SSRF). http/https only, 2 MB cap. |
| `get_weather(place?)` | read | Open-Meteo geocoding + forecast (free, no key, non-commercial). Default place from a new `home_city` preference. |
| `calculate(expression)` | read | Safe `ast` evaluator: arithmetic, powers (cap size), common maths functions, `pi`, `e`. Never `eval`. |
| `list_files(folder?, search?)` | read | No arguments → the approved folders. Only inside `settings.workspace` (Documents/JARVIS) and `prefs["allowed_folders"]` (already validated by `prefs.clean_folder`). Resolve paths and check `is_relative_to` a root; refuse `.env`, keys, `.ssh`, `.git`. |
| `read_file(path, offset?)` | read, **untrusted output** | Text, `.docx` and `.pptx` (stdlib zipfile + XML), `.pdf` (add `pypdf`). ≤ ~2,800 chars per call with a "continue at offset N" note. |
| `write_file(path, content, mode)` | create/append = act; **overwrite = sensitive** | Uses the per-call risk from item 1. No delete, move or rename yet. |
| `open_file(path)` | act | `os.startfile` on Windows; same folder rules. |
| `set_reminder`, `list_reminders`, `cancel_reminder` | act / read / act | See item 4. |
| `pc_control(action, value?)` | act | Windows only via `ctypes` `keybd_event`: play_pause, next, previous, volume_up, volume_down, mute, set_volume (50 volume-down presses, then value/2 volume-up presses; say it can't read the level back), lock (`LockWorkStation`). Put it behind a small class so tests inject a fake, like `FakeLauncher` in `tests/conftest.py`. |

Keep every description short: all tool schemas together should stay under about
1,700 tokens (2.0's seven tools use about 650). Add a Settings row for approved
folders (the `allowed_folders` preference already exists) and for `home_city`.
Teach `jarvis/llm/fake.py` (`scripted_reply`) a phrase per new tool so the demo
brain and the browser run can exercise them.

### [ ] 4. Reminders
- Scheduler: one asyncio task, every 15 s, picks `pending` reminders that are due.
- Deliver to: (a) the app, through a small `GET /api/notices?after=` poll that
  shows a banner; (b) Telegram if linked (also append the reminder as an
  assistant message in the Telegram conversation so "snooze 10 minutes" has
  context); (c) a Windows toast via PowerShell, best effort.
- Reminders missed while the PC was off are delivered at start-up, marked late.
- `set_reminder` takes `text` plus `at` (local ISO date-time; the system prompt
  already gives the current local time) or `in_minutes`, and optional `repeat`.

### [ ] 5. Interface, browser run, docs, release
- Settings sections (Phone, Folders, Home city), reminders list, phone icon on
  Telegram conversations.
- Extend `tests/e2e/run_e2e.py`; look at the screenshots.
- Bump version to 2.1.0 in `pyproject.toml` and `jarvis/__init__.py`; update
  `CHANGELOG.md`, the status table in `docs/ROADMAP.md`, `docs/DECISIONS.md`
  (D24 Telegram, D25 ddgs, D26 Open-Meteo, D27 pypdf), `README.md`,
  `.env.example`, and this file.
- Mark the pull request ready; tell Jack to merge it, run `update.bat`, and what to try.

### After 2.1
- **2.2 Voice:** microphone button, Groq Whisper speech-to-text (free: 20
  requests/min, 2,000/day), spoken replies with Edge's natural British voices,
  interrupt. Then transcribe Telegram voice notes the same way.
- **2.3:** to-dos; close apps; move/delete files with approval.
- **3.0:** multi-step plans that survive restarts; semantic memory if needed;
  the full app on iPhone/iPad (Tailscale was the recommended route: free
  Personal plan, private, no open ports).

## Facts checked on 10 November 2026 (re-check before relying on them later)

- **Telegram Bot API:** free, no plan or card; long polling needs outbound HTTPS only.
- **Tailscale:** Personal plan free (6 users, unlimited personal devices). Not chosen for now.
- **Search:** `ddgs` needs no key (unofficial scraping, can be rate-limited).
  Brave Search API now needs a card ($5 monthly credit). Tavily: 1,000 free
  credits/month, no card (a possible later upgrade). **Groq's built-in
  `browser_search` is priced ($5 per 1,000 searches): do not use it.**
- **Open-Meteo:** free without a key for non-commercial use (under 10,000 calls/day).
- **Other models:** the OpenAI API has no free tier, and a ChatGPT subscription
  does not include API use. GitHub Models was retired on 30 July 2026. Gemini's
  free tier still exists (Flash-Lite about 500 requests/day; Flash only about 20)
  and Google may use free-tier prompts for training. JARVIS already supports a
  Gemini or OpenRouter key as a fallback in Settings.

## How to work on it

```bash
uv sync                                         # install
uv run pytest -q                                # must pass before every commit
uv run jarvis serve --no-browser --port 8765    # run
JARVIS_MODELS=fake:agent uv run jarvis serve    # scripted demo brain, no key needed
python tests/e2e/run_e2e.py                     # browser run (needs Playwright + Chrome)
```

Jack updates his PC by merging the pull request on GitHub, then double-clicking
`update.bat` (which runs `git pull` and `uv sync`), then `start.bat`.

### Where things are
| Path | What it is |
|---|---|
| `jarvis/agent.py` | The turn loop: context → model → tools (validate, permission, approval, run, log) → reply → background learning |
| `jarvis/persona.py` | The system prompt: character, dials, standing instructions, capability list |
| `jarvis/memory.py` | Memory rules, what goes into each prompt, automatic learning, summaries |
| `jarvis/storage.py` | SQLite: numbered migrations, full-text search, all queries |
| `jarvis/tools/` | `base.py` (registry, risk, validation), `memory_tools.py`, `system_tools.py` |
| `jarvis/llm/` | `openai_compat.py` (one client for all providers), `router.py` (fallback, rate limits), `fake.py` (scripted test brain) |
| `jarvis/runtime.py` | Wires everything together; keys; model checks |
| `jarvis/server.py` | FastAPI routes; every `/api` call needs the session token, a local Host and same-origin |
| `jarvis/prefs.py`, `config.py` | App-changeable preferences (database) and fixed settings (`.env`) |
| `jarvis/web/` | Interface: `index.html`, `css/app.css`, `js/{main,chat,pages,settings,render,core,api,util}.js`, `vendor/` |
| `tests/` | `conftest.py` (fixtures: `scripted_runtime`, `run_turn`, `Client`), unit tests, `e2e/` (mock provider + Playwright run) |
| `docs/` | `ARCHITECTURE.md`, `DECISIONS.md` (D1–D23), `ROADMAP.md` (status with evidence), `WORKLOG.md` |

### Things that will trip you up
- A tool-using turn makes at least two model requests; with the 8,000 tokens/min
  limit the second often lands on the fallback model. That is expected. Three or
  more steps may pause up to 30 s ("Rate limit reached. Resuming in N s").
- Tests script the model with `scripted_runtime(settings, [reply1], [reply2], …)`;
  background learning is off there unless `learn=True`.
- Anything returning outside content (web pages, files) must set
  `untrusted_output=True`: after that, every action in the same turn needs approval.
- The Windows-only paths (Start-menu app launch, Edge app window, `setup.bat`)
  can't be run on Linux build machines. Say so; don't mark them tested.
- Python 3.10 compatibility: no `datetime.UTC`, no `itertools.batched`, no PEP 695 syntax.

## Keeping this handoff alive

Before every commit: tick boxes above, update "Current state" and "Last updated",
and add an entry at the top of `docs/WORKLOG.md` (what changed, what was verified
and how, what is unverified, what comes next). Commit small, push often. If you
stop mid-task, write down exactly where under "What to do next".
