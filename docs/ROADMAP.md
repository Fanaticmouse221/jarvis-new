# Roadmap and status

Status words used here, and nowhere more generously than the evidence allows:

- **Tested and working**: covered by automated tests *and* exercised in a real browser.
- **Built, needs a real-world check**: tested against a stand-in, but not yet on Jack's PC or against the live service.
- **Planned** / **Not started**.

## Where things stand (v2.3.0 in development, 10 November 2026)

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
| **Opening and closing apps on Windows** | **Built, needs a real-world check** | Uses the Start menu app list and bounded process matching; only injected/fallback behaviour could be run here |
| Opening web pages, system status | Tested and working | Tests (system status reads real values) |
| Rate-limit handling and fallback | Tested and working | Tests; browser run with a simulated 429 |
| Usage and remaining allowance | Tested and working | Shown in Settings from stored usage and provider headers |
| First-run key entry | Tested and working | Browser run: rejected key refused, accepted key saved, models chosen |
| API protected from other web pages | Tested and working | Tests for missing token, foreign origin, foreign host |
| Maths, code and tables | Tested and working | Browser run |
| Phone-sized layout | Tested and working | Browser run, including a 390px viewport |
| Telegram phone chat | Built, needs a real-world check | Unit tests and browser run against a Telegram API stand-in; live bot and phone pairing remain unverified |
| Web search and public-page reading | Built, needs a real-world check | Unit tests and browser run against stand-ins; upstream search throttling and live sites remain unverified |
| Weather and safe calculator | Built, needs a real-world check | Unit tests; live Open-Meteo access is not available in the build environment |
| Approved-folder file tools | Built, needs a real-world check | Unit tests and browser run against test folders; Windows document associations remain unverified |
| Reminders and delivery | Built, needs a real-world check | Unit tests and browser run with app/Telegram stand-ins; Windows toast delivery remains unverified |
| **Own window, desktop shortcut, setup on Windows** | **Built, needs a real-world check** | Windows-only code paths |
| Browser voice messages | Built, needs a real-world check | Unit/API tests and browser regression cover the microphone control and status feedback; live Groq Whisper, microphone permission and speech quality remain unverified |
| To-dos, closing apps and approved file actions | Built, needs a real-world check | Durable editable to-dos with optional due dates and approval-gated deletion, approval-aware close/move/delete tools, safer process matching, and API edit parity are covered by 188 automated tests and a 63-check browser regression; real Windows process/file behaviour and live-model phrasing remain unverified |
| Multi-step work that survives restarts | Built, needs a real-world check | Durable plan/step storage, create/list/step-change agent tools, protected API routes and visible plan controls are covered by 193 automated tests and a 65-check browser regression; resumable execution remains unbuilt |
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
| Voice | Not attempted in 2.1 |

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

### 2.1 Reach (released 10 November 2026)
- [x] Shared plumbing: schema v3, channels, dynamic risks and lifecycle
- [x] Message JARVIS from a phone through a private Telegram bot, with approval buttons
- [x] Web search and page reading with bounded, untrusted results
- [x] Weather and safe calculator
- [x] Files: find, read (text, Word, PowerPoint, PDF), create in folders Jack approves; overwriting always asks
- [x] Reminders, delivered in the app, on the phone and as a best-effort Windows notification
- [x] Media, volume and screen lock on the PC
- [x] Settings and browser regression coverage for the Reach interface

### 2.2 Voice (in progress)
- [x] Microphone button and protected browser transcription endpoint
- [x] Speech-to-text through Groq's hosted Whisper (free tier: 20 requests a minute, 2,000 a day)
- [x] Automatic spoken replies through browser speech synthesis
- [x] Hands-free mode with sustained-silence detection and a two-minute recording limit
- [x] Interrupt recording or speech by tapping the microphone control; listening / transcribing / speaking status is visible
- [ ] Voice notes sent through Telegram
- [ ] Wake phrase investigated after the basics are solid

### 2.3 Tasks
- [x] Durable to-dos with add, list, complete, reopen, edit, due dates and approval-gated deletion
- [x] To-dos page with direct add, completion controls and due-date display
- [x] Closing apps; moving/deleting files with approval
- [x] Safer application process matching and automatic update before startup

### 3.0 and beyond
- [x] Durable plan records with ordered steps and create/list API and agent tools
- [x] Step completion/reopening with plan status derived from persisted steps
- [x] Resume lookup for the next pending plan step
- [x] Visible plan creation and step controls in the To-dos page
- [ ] Resumable execution
- [ ] Semantic memory search if keyword recall proves insufficient
- [ ] Login, encrypted remote access, installable app on iPhone and iPad, sync
- [ ] Calendar and email through official APIs, with approval before sending

## Known limitations in 2.3
- The demo brain (`fake:agent`) is a script, not an AI. It understands a few phrasings only.
- Stopping or reloading the page mid-task cancels that task.
- The console window stays open while JARVIS runs.
- Automatic learning costs one extra small model request for messages that look personal.
