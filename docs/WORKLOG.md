# Work log

Newest entry first. One entry per working session or pushed piece of work: what
changed, what was verified and how, what is still unverified, what comes next.
Releases are summarised in `CHANGELOG.md`; the plan lives in `HANDOFF.md`.

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

**Next:** open/merge the 2.1 release pull request, then begin the 2.2 voice
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
