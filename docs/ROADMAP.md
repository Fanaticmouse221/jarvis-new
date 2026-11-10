# Roadmap and status

Status words used here, and nowhere more generously than the evidence allows:

- **Tested and working**: covered by automated tests *and* exercised in a real browser.
- **Built, needs a real-world check**: tested against a stand-in, but not yet on Jack's PC or against the live service.
- **Planned** / **Not started**.

## Where things stand (v2.0.0, 10 November 2026)

| Capability | Status | Evidence, or what is missing |
|---|---|---|
| Text conversation, streaming | Tested and working | 67 tests; browser run of 39 checks |
| **A real reply from Groq** | **Built, needs a real-world check** | The build environment cannot reach Groq. The client is tested against a mock that speaks the same protocol. First `check.bat` on Jack's PC settles it. |
| **Personality: how JARVIS actually sounds** | **Built, needs a real-world check** | The prompt is tested for content; tone can only be judged with a real model. |
| Personality dials and standing instructions | Tested and working | Changes reach the model on the next message (verified in the browser run) |
| Memory: told (`remember`) | Tested and working | Stored in the database; recalled after a restart |
| Memory: learned automatically | Tested and working with a stand-in model | Extraction quality with a real model needs a real-world check |
| Memory: survives restart | Tested and working | Browser run restarts the server and asks "what do you know about me?" |
| Memory screen (search, add, edit, pin, delete, export) | Tested and working | API tests; browser run |
| Long conversations keep a summary | Tested and working | Unit test; summary quality needs a real model |
| Search across past conversations | Tested and working | Tests; sidebar search in browser run |
| Tool calling with real execution | Tested and working | A launched program wrote a marker file, checked independently |
| Approvals (allow, decline, always allow, stop) | Tested and working | Tests; browser run confirms nothing runs before approval |
| Action log | Tested and working | Browser run |
| **Opening apps on Windows** | **Built, needs a real-world check** | Uses the Start menu app list; only the non-Windows fallback could be run here |
| Opening web pages, system status | Tested and working | Tests (system status reads real values) |
| Rate-limit handling and fallback | Tested and working | Tests; browser run with a simulated 429 |
| Usage and remaining allowance | Tested and working | Shown in Settings from stored usage and provider headers |
| First-run key entry | Tested and working | Browser run: rejected key refused, accepted key saved, models chosen |
| API protected from other web pages | Tested and working | Tests for missing token, foreign origin, foreign host |
| Maths, code and tables | Tested and working | Browser run |
| Phone-sized layout | Tested and working | Browser run (layout only; no remote access yet) |
| **Own window, desktop shortcut, setup on Windows** | **Built, needs a real-world check** | Windows-only code paths |
| Voice | Not started | Milestone 2.1 |
| Web research | Not started | Milestone 2.2 |
| File tools | Not started | Milestone 2.2 |
| Reminders and tasks | Not started | Milestone 2.3 |
| Multi-step work that survives restarts | Not started | 3.0 |
| iPhone / iPad access, sync | Not started | 3.x |

## Acceptance criteria

| Criterion | Result |
|---|---|
| A saved preference is recalled accurately after restarting | Met (stand-in model). Repeat on Jack's PC with Groq. |
| An approved task produces a real, independently verifiable result | Met: launched program's marker file |
| Sensitive actions require approval; credentials are not exposed | Met: approval tests; key shown only as its last four characters |
| Conversations and settings survive restarts | Met |
| Common failures give useful messages, not crashes | Met: bad key, no key, rate limit, oversize request, tool failure, model failure mid-task |
| Messages produce legitimate model responses | **Open** until the first live run |
| JARVIS sounds like JARVIS | **Open** until judged with a real model |
| Voice, research | Not attempted in 2.0 |

## Done

### 2.0 "A mind of its own" (2026-11-10)
- [x] Assessment of 1.0 ([ASSESSMENT-1.0](ASSESSMENT-1.0.md))
- [x] Long-term memory: store, retrieval into every reply, automatic learning, corrections, management screen, export
- [x] Rolling conversation summaries; search across conversations
- [x] Personality: rewritten character with tone examples, three dials, standing instructions, "teach JARVIS" on any reply
- [x] Agent core: tool calling, validated arguments, permissions, approvals, step limit, action log
- [x] First real actions: open apps, open web pages, system status
- [x] Model layer: tool-call streaming, rate-limit rests, usage tracking, oversize recovery, automatic model selection
- [x] Local API protection
- [x] New interface: chat with live steps, Memory, Activity, Settings with system status; first-run setup; maths and code; regenerate, edit, export, search
- [x] 67 automated tests, a mock provider and a 39-check browser run

### 0.1 Text chat foundation (2026-11-09)

## Next

> The order changed on 10 November 2026 at Jack's request: phone access and more
> abilities come first. The detailed, current plan is in [`HANDOFF.md`](../HANDOFF.md).

### 2.1 Reach: phone, web, files, reminders (in progress on branch `jarvis-2.1`)
- [ ] Message JARVIS from a phone through a private Telegram bot, with approval buttons
- [ ] Web search and page reading with sources
- [ ] Weather, calculator
- [ ] Files: find, read (text, Word, PowerPoint, PDF), create in folders Jack approves; overwriting always asks
- [ ] Reminders, delivered in the app, on the phone and as a Windows notification
- [ ] Media, volume and screen lock on the PC

### 2.2 Voice
- [ ] Microphone button and hands-free mode with silence detection
- [ ] Speech-to-text through Groq's hosted Whisper (free tier: 20 requests a minute, 2,000 a day)
- [ ] Spoken replies using the natural British voices built into Edge, sentence by sentence
- [ ] Interrupt by key or tap; listening / thinking / speaking shown by the Core
- [ ] Voice notes sent through Telegram
- [ ] Wake phrase investigated after the basics are solid

### 2.3 Tasks
- [ ] To-dos; closing apps; moving and deleting files with approval

### 3.0 and beyond
- [ ] Multi-step work with visible plans that survives restarts
- [ ] Semantic memory search if keyword recall proves insufficient
- [ ] Login, encrypted remote access, installable app on iPhone and iPad, sync
- [ ] Calendar and email through official APIs, with approval before sending

## Known limitations in 2.0
- The demo brain (`fake:agent`) is a script, not an AI. It understands a few phrasings only.
- Stopping or reloading the page mid-task cancels that task.
- The console window stays open while JARVIS runs.
- Automatic learning costs one extra small model request for messages that look personal.
