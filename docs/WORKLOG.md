# Work log

Newest entry first. One entry per working session or pushed piece of work: what
changed, what was verified and how, what is still unverified, what comes next.
Releases are summarised in `CHANGELOG.md`; the plan lives in `HANDOFF.md`.

---

## 10 Nov 2026 · GitHub Copilot · Due-date regression coverage

**Done:** extended the API and browser regression to verify due-date
normalisation and display. The browser now creates a dated to-do through the
real page, confirms the deadline is rendered, then continues the existing
completion and reopen checks.

**Verified:** `uv run pytest -q` passed **185 tests**. The browser regression
passed **63 checks** with no console errors or warnings.

**Unverified:** localised date formatting and natural-language due-date
interpretation still need a real Windows/live-model check.

**Next:** commit and merge this evidence improvement, then continue development.

## 10 Nov 2026 · GitHub Copilot · Automatic update before start

**Done:** changed `start.bat` to call `update.bat /silent` before checking
dependencies and launching JARVIS. The updater now returns cleanly without
pausing when called with `/silent`, while direct double-click use keeps its
existing pause and completion message. A failed update stops the launch.

**Verified:** the batch-file changes were inspected for `call`/`errorlevel`
control flow, and the full Python suite passed **185 tests**. The browser
regression remains at **62 checks** from the preceding verified slice.

**Unverified:** actual `git pull`, `uv sync` and the resulting server launch
need to be exercised on Jack's Windows PC.

**Next:** commit and merge this startup-flow change, then verify it on Windows.

## 10 Nov 2026 · GitHub Copilot · To-do due dates

**Done:** added optional ISO due dates to durable to-dos. SQLite migration v5
stores and normalises UTC timestamps, the agent can include due dates when
creating and listing items, and the To-dos page provides a local date/time
picker with overdue highlighting. Existing items and API callers remain
compatible when no due date is supplied.

**Verified:** `uv run pytest -q` passed **184 tests**. The browser regression
passed **62 checks** with no console errors or warnings. Python and JavaScript
syntax checks plus `git diff --check` passed.

**Unverified:** date display depends on the user's local Windows timezone, and
live-model interpretation of natural-language due dates still needs a real
Groq check.

**Next:** commit and merge this slice, then continue with the next small task
ability.

## 10 Nov 2026 · GitHub Copilot · Safer application process matching

**Done:** tightened the shared process matcher used by app opening
confirmation and closing. It now strips executable suffixes, requires
distinctive tokens and only permits short internal fragments when the process
name is very close in length, reducing the chance that a generic app-name
fragment targets an unrelated process. Added regression cases for valid
`Code.exe`/`msedge.exe` matches and false positives such as `decoder.exe`.

**Verified:** `uv run pytest -q` passed **184 tests**. The browser regression
passed **62 checks** with no console errors or warnings. Python syntax checks
and `git diff --check` passed.

**Unverified:** real Windows process names and application close behaviour still
need a check on Jack's PC; the browser run uses the injected launcher.

**Next:** commit and merge this hardening, then continue with the next small
2.3 or 3.0 slice.

## 10 Nov 2026 · GitHub Copilot · To-dos browser coverage

**Done:** extended the browser regression to navigate the real To-dos page,
add a to-do through the protected API, complete it and reopen it. The check
also returns to Chat before continuing the existing conversation coverage.

**Verified:** the complete browser regression passed **62 checks** with no
console errors or warnings. The new browser test file passes Python syntax and
`git diff --check`.

**Unverified:** this remains a stand-in model and test workspace; live-model
task phrasing and real Windows application/file behaviour still need Jack's PC.

**Next:** commit and merge this regression coverage, then continue with the
next small 2.3 ability.

## 10 Nov 2026 · GitHub Copilot · 2.3 approved computer and file actions

**Done:** completed the remaining planned 2.3 action slice. Added sensitive
`close_app`, `move_file` and `delete_file` tools. Closing uses the selected
application's distinctive process tokens, terminates matching processes and
reports when nothing is running. File moves and deletes are restricted to
approved roots, re-check paths immediately before mutation, refuse move
overwrites and only delete regular files. Added fake-model phrases and focused
tests for execution, bounds and approval injection.

**Verified:** `uv run pytest -q` passed **183 tests**. The browser regression
passed **58 checks** with no console errors or warnings. Python syntax checks,
Node syntax checks and `git diff --check` passed.

**Unverified:** real Windows application process matching, unsaved-work
behaviour, Windows file associations, live Groq interpretation and live voice
paths still need Jack's PC. The browser run uses injected launchers and test
folders for destructive actions.

**Next:** commit and merge this slice, then continue with the next small 2.3
ability or a real-world check of the new actions.

## 10 Nov 2026 · GitHub Copilot · 2.3 to-dos foundation

**Done:** moved on from Telegram voice notes as requested and added the first
2.3 Tasks slice. SQLite migration v4 stores durable to-dos with pending and
completed states; `add_todo`, `list_todos` and `change_todo` use the standard
agent permissions, action log and conversation context. Added protected API
routes and a To-dos page for direct add, complete and reopen actions. Telegram
text support was left unchanged.

**Verified:** `uv run pytest -q` passed **181 tests**. The browser regression
passed **58 checks** with no console errors or warnings. Node syntax checks and
`git diff --check` passed.

**Unverified:** live-model interpretation of task phrases, live Groq access and
Windows-only voice behaviour remain unverified. Closing apps and moving/deleting
files are still not implemented.

**Next:** add the remaining approval-aware computer/file actions for 2.3, then
open the next pull request.

---

## 10 Nov 2026 · GitHub Copilot · voice controls checkpoint

**Done:** extended the browser voice foundation with visible listening,
transcribing and speaking status, tap-to-stop recording, speech interruption,
automatic stop after 2.5 seconds of sustained silence, and a two-minute
recording limit. Audio tracks and the analyser are cleaned up when recording
ends or fails. Added a browser assertion for the status element.

**Verified:** `node --check` passed for the browser JavaScript,
`git diff --check` passed, `uv run pytest -q` passed **178 tests**, and the
browser regression passed **57 checks** with no console errors or warnings.

**Unverified:** real microphone permissions, silence thresholds across devices,
live Groq Whisper access, transcription accuracy and speech quality still need
Jack's Windows PC. Telegram voice notes are not implemented.

**Next:** route Telegram voice notes through the same bounded transcription
service, then run a real-world Windows voice check before calling 2.2 complete.

---

## 10 Nov 2026 · GitHub Copilot · voice foundation

**Done:** added the first 2.2 voice slice. The browser microphone button records
audio with `MediaRecorder`; the protected `/api/transcribe` route sends it to
Groq Whisper without storing audio; the transcript enters the normal chat flow;
and voice-originated replies are spoken automatically by browser speech
synthesis. Added provider error handling, a configurable transcription model,
and API tests.

**Verified:** `uv run pytest -q` passed **178 tests**. The browser regression
passed **56 checks** after fixing a voice initialisation issue; the browser
asserts the microphone control exists and reported no console errors. `git diff
--check` passed.

**Unverified:** live Groq Whisper access, microphone permission behaviour,
transcription accuracy, speech voice quality and Telegram voice notes require
Jack's Windows PC and real credentials.

**Next:** add recording-state feedback, interruption and silence detection, then
send Telegram voice notes through the same transcription path.

---

## 10 Nov 2026 · GitHub Copilot · 2.1 release pass

**Done:** finished the Reach release metadata and interface coverage. Bumped the
package to 2.1.0, updated the README, changelog, architecture and roadmap, and
recorded the current handoff state. The browser regression now explicitly checks
the Folders and home-city settings and the Reminders section.

**Verified:** `uv run pytest -q` passed **176 tests**. The browser regression
passed **55 checks** against the OpenAI and Telegram stand-ins; generated
screenshots were inspected, including Settings, linked Phone, Telegram
conversation and 390px mobile views. `git diff --check` passed.

**Unverified:** this environment cannot perform a live Groq request, pair a real
Telegram bot, or verify Windows toast delivery and document associations. The
browser run uses stand-ins for those services.

**Next:** merge [PR #5](https://github.com/Fanaticmouse221/jarvis/pull/5), then begin the 2.2 voice
milestone. On Jack's PC, run `update.bat`, then try a real Groq reply, Telegram
pairing and a reminder.

---

## 10 Nov 2026 · ChatGPT/Codex · reminders checkpoint

**Done:** persistent one-off/daily/weekday/weekly reminders, 15-second scheduler,
start-up delivery of missed reminders, durable app notices, linked-phone delivery
with conversation context, and best-effort Windows toast. Added protected list,
cancel and notices routes, Settings list, app banners, and demo reminder phrases.
The outbox retains 500 occurrences, the app feed exposes the newest 200, and
pending phone retries expire after seven days. Sends are bound to the paired owner.

**Evidence / limits:** 13 earlier reminder unit tests passed; later focused plumbing
and reminder run passed 22. Final owner/retention fixes and all integration/UI
changes are unverified, as requested. Actual Windows toast delivery was not tried.
Telegram cannot promise exactly-once sends if the process dies after sending but
before recording its acknowledgement.

**Next:** finish version 2.1 documentation and make PR #4 ready for review.

---

## 10 Nov 2026 · ChatGPT/Codex · new tools checkpoint

**Done:** registered search, public page reading with pinned DNS/redirect checks,
weather, calculator, approved-folder file tools and Windows media/volume/lock.
Added Home city and Folders settings, compact schemas and demo phrases. Overwrite
always requests approval; file text preserves whitespace. pypdf and ddgs are the
only new direct dependencies. Reminder tools are wired in the next checkpoint.

**Evidence / limits:** earlier 67 tool tests and live read-only search/page/weather
probes passed. A later PDF resource-limit test exposed an invalid blank-PDF fixture;
its fixture was corrected statically. That correction, final PDF limits, registration
and UI integration are unverified because Jack asked to stop all testing. Windows
controls used fakes only; no real lock or volume command was issued.

**Next:** integrate scheduler, reminders list, durable app notices, then release docs.

---

## 10 Nov 2026 · ChatGPT/Codex · Telegram checkpoint

**Done:** private owner pairing with limited guesses, outbound long polling,
queued shared-agent turns, independent approval callbacks and stop, phone-format
replies, safe HTML fallback, token verification/persistence, protected API and
Phone settings. Draft pull request: https://github.com/Fanaticmouse221/jarvis/pull/4.

**Verified before Jack stopped testing:** full working-tree suite passed 175
tests, including the new tool/reminder modules being prepared for later commits;
15 Telegram service tests and 2 protected API/token tests were covered. The extended
browser run had also finished with 51 checks before testing stopped, including
12 phone-flow checks. Its phone screenshots were not subsequently inspected.
No live bot credentials were used.

**Unverified / instruction:** Jack explicitly said "no need to test itll be fine
stop testing". All further testing stopped; subsequent fixes and integration
are implementation only, not a claim of a tested release. Owner/generation binding
for asynchronous reminder sends and resilient unexpected-error handling were added
after the last run. The extended browser
runner is included for later use. OneDrive dependency locks were avoided by using
an isolated temporary Python environment for the completed checks.

**Next:** register the new tools, finish reminder/UI integration and release docs.

---

## 10 Nov 2026, 11:00 AM · ChatGPT/Codex · plumbing checkpoint

**Done:** created `codex/jarvis-2.1-reach` from merged `main`. Added schema v3,
conversation channels, per-call risk assessment, dynamic missing capabilities,
phone-specific formatting context and server lifecycle management. Made the
browser runner portable to Windows with an isolated launcher that starts a real
Python subprocess and verifies its marker file; it never deletes an existing run.

**Verified:** original 67 tests passed before changes; 76 passed after plumbing.
Chrome browser run passed all 39 checks, including restart, approvals and memory.
Inspected desktop approval and mobile conversation screenshots.

**Unverified:** live Telegram, live Groq and Windows Start-menu launch. The browser
launcher deliberately uses an isolated test application.

**Next:** item 2 Telegram service, protected API, phone settings and fake-API tests.

---

## 10 Nov 2026, 11:00 AM · Claude · branch `jarvis-2.1`

**Done**
- Jack installed 2.0 on his Windows PC. `setup.bat` ran (he first typed
  `\setup.bat`; PowerShell needs `.\setup.bat`) and he reported "that works good".
- Jack asked for: phone messaging, more abilities, continued development, and a
  handoff system so another AI can continue when one hits its usage limit.
- Asked Jack how he wants phone access. **He chose a Telegram bot.**
- Researched free options and recorded the findings in `HANDOFF.md` ("Facts
  checked"): Telegram Bot API, Tailscale, search providers, Open-Meteo, other
  model providers (GitHub Models retired; OpenAI API has no free tier).
- Read the whole 2.0 codebase and wrote the design for 2.1 into `HANDOFF.md`.
- Added the handoff system: `HANDOFF.md` (including how to hand over and how to
  hand back), `AGENTS.md` (same rules as `CLAUDE.md`), this log, and
  `save-work.bat` (commits and pushes everything, for when an AI can't push itself). Updated the roadmap order (2.1 is now phone + abilities; voice is 2.2).

**Verified**
- Nothing new to verify: this commit is documentation only. `main` is unchanged
  (67 tests and the 39-check browser run passed when 2.0 was released).

**Not done / unverified**
- **No 2.1 feature code exists yet.** Start at item 1 of "What to do next" in `HANDOFF.md`.
- `save-work.bat` is plain git commands but has not been run on Windows.
- Still unconfirmed on Jack's PC: memory after a restart, opening apps, how the
  personality sounds with the real model.

**Next**
- `HANDOFF.md` → "What to do next", items 1 to 5 in order.

---

## 10 Nov 2026, morning · Claude · branch `jarvis-2.0` → `main` (PR #1)

**Done:** JARVIS 2.0. Assessment of 0.1 (`docs/ASSESSMENT-1.0.md`); long-term
memory; personality; agent loop with tools, permissions and approvals; new
interface; model layer with fallback and rate-limit handling; local API protection.
Details in `CHANGELOG.md`; decisions D11–D23 in `docs/DECISIONS.md`.

**Verified:** 67 automated tests; a 39-check Playwright browser run against a
mock provider, including a server restart ("what do you know about me?").

**Unverified at the time:** live Groq replies, tone with a real model, quality
of automatic learning with a real model, all Windows-only paths.

---

## 9 Nov 2026 · Claude · `main`

**Done:** v0.1.0. Hardware check of Jack's laptop, stack chosen (D1–D10), text
chat with streaming, saved conversations, model fallback, Windows setup scripts.
