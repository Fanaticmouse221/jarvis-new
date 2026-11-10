# Changelog

## 2.2.0 (in development): Voice

- Added a browser microphone button that records audio locally and sends it to
  the protected JARVIS server for Groq Whisper transcription.
- Voice transcripts use the normal chat, memory and tool flow; replies are
  spoken automatically with the browser's available speech synthesis voice.
- Added listening, transcribing and speaking status feedback, tap-to-stop
  recording, speech interruption, sustained-silence auto-stop and a two-minute
  recording limit.
- Added clear handling for missing keys, denied microphone access, empty or
  oversized recordings, rate limits and provider failures.

## 2.3.0 (in development): Tasks

- Added durable SQLite-backed to-dos with add, list, complete and reopen actions.
- Added a To-dos page alongside Chat, Memory, Activity and Settings.
- JARVIS can manage the same to-dos through the normal permission-aware agent path.
- Added approval-aware `close_app`, `move_file` and `delete_file` actions.
- Close-app matching reports real process results; file mutations stay within
  approved folders, refuse move overwrites and never recursively delete folders.
- Added optional due dates to to-dos, with UTC storage and overdue highlighting
  in the To-dos page.
- Added approval-gated deletion for to-dos and explicit overdue labels in agent
  listings.
- JARVIS can now revise a to-do's title, details or due date.
- The protected to-do API now supports the same title, details and due-date
  edits as the agent tool.
- Added the first durable-plan foundation: ordered plan steps survive restarts
  and are available through protected API and agent create/list tools.
- Plan steps can now be completed or reopened, with the parent plan becoming
  completed only when every step is complete.
- The To-dos page now shows durable plans, creates plans from one-step-per-line
  input, and lets Jack complete or reopen persisted steps.
- JARVIS can inspect a plan and report its next pending step after a restart.
- Plans can be cancelled and reopened without losing their step history.
- Plan listings now show the next pending step when one exists.
- `start.bat` now updates JARVIS automatically before launching it.

## 2.1.0 (2026-11-10): Reach

- Channel-aware conversations, dynamic tool risks and background service lifecycle.
- Capability descriptions now follow the tools that are switched on.
- Browser regression runner supports Windows and uses isolated test data.
- Private Telegram phone chat, pairing, approval buttons and Phone settings.
- Web search, bounded public-page reading, Open-Meteo weather and safe arithmetic.
- Approved-folder document reading and text writing; overwrites always ask.
- Windows media, volume and lock controls; approved folders and home-city settings.
- Persistent repeating reminders with app banners, Telegram delivery and best-effort Windows notifications.

## 2.0.0 (2026-11-10): a mind of its own

Memory and personality are the centre of this release; the agent core exists to serve them.

### Memory
- Long-term memory in the database: standing instructions, preferences, facts about you, projects, notes
- What JARVIS knows is sent with every message (everything while it is small; pinned, relevant and recent once it grows)
- Learns two ways: the model saves what you tell it (`remember`), and a background pass notes lasting things you mention; both shown in the conversation, the latter with Undo
- Corrections replace the old memory; near-duplicates are merged; passwords, keys and card numbers are refused
- Memory screen: search, add, edit, pin, delete, export, switch off, forget everything
- Rolling summaries keep the thread of long conversations; search across all past conversations

### Personality
- Rewritten character with situational registers and original tone examples
- Dials for manner, humour and answer length; your name and form of address; free-text instructions
- Standing instructions learned from what you say, or added with "Teach JARVIS" on any reply
- Time-aware greeting; offers to continue the last conversation; knows recent conversation titles

### Agent and tools
- Real tool calling: validated arguments, permissions (allowed / ask first / off), approvals in the conversation, step limit, timeouts
- Tools: remember, recall, forget, search past conversations, open an app, open a web page, check system status
- Every action recorded with its real outcome in an Activity log
- Outside-content rule in place for the web and file tools to come

### Models
- Streaming tool calls, usage and rate-limit headers; rate-limited models rest while the next answers
- Oversized requests retried with less history; optional fields a provider rejects are dropped
- Add a key in the app: checked with the provider, saved to `.env`, models chosen from what your account offers
- Default fallback is now `openai/gpt-oss-20b`; output capped at 2,048 tokens to fit Groq's free tier

### Interface
- Redesigned: Chat, Memory, Activity, Settings (with system status); first-run setup; own window via Edge; desktop shortcut
- Maths (KaTeX), code highlighting, tables; regenerate, edit and resend, export, sidebar search
- Libraries and fonts bundled locally; no CDN

### Security
- API accepts calls only from JARVIS's own page (session token, host and origin checks)

### Under the hood
- Database migrates from 0.1 in place
- Automated tests, a mock provider and a browser regression runner covering the app and Telegram stand-in in `tests/e2e`
- `update.bat`

### Not in this release
Voice, to-dos, closing apps, and moving or deleting files. See the roadmap.

## 0.1.0 (2026-11-09): text chat foundation
- Web chat with streaming replies, saved conversations, model fallback, Windows setup scripts
