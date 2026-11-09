# Roadmap

✅ done · 🔜 next · ⏳ planned

## ✅ Phase 1: Functional foundation (v0.1.0, 2026-11-09)
- [x] Technology stack chosen and documented ([DECISIONS](DECISIONS.md))
- [x] Project structure, Windows setup/start/check scripts
- [x] Web chat interface with streaming replies and Markdown rendering
- [x] Free cloud models via Groq, with ordered fallback across providers
- [x] JARVIS personality, honest about current capabilities
- [x] Persistent conversations (SQLite): list, open, rename, delete
- [x] Offline demo mode; `jarvis check` connection tester
- [x] Test suite (35 tests) and an automated browser smoke test

**Success condition:** reliable text conversations. *Confirm on Jack's PC with a real Groq key.*

## 🔜 Phase 2: Voice assistant
Planned approach (to confirm before building):
- [ ] Push-to-talk microphone button in the web UI (browser captures audio)
- [ ] Speech-to-text: [faster-whisper](https://github.com/SYSTRAN/faster-whisper) running locally on the CPU (free, private); Groq's hosted Whisper as a faster option
- [ ] Text-to-speech: a local neural voice (Piper or Kokoro), with a composed, British-leaning voice
- [ ] Speak replies sentence by sentence while text streams, for low latency
- [ ] Interrupt: talking or pressing a key stops JARVIS speaking
- [ ] Optional wake phrase "JARVIS" (openWakeWord), desktop only
- [ ] Voice stays optional; everything still works by text

**Success condition:** a natural back-and-forth spoken conversation.

## ⏳ Phase 3: Memory and personalisation
- [ ] `memory/` module: facts, preferences and project notes in SQLite
- [ ] Relevant memories retrieved into each conversation's context
- [ ] JARVIS proposes memories; the user approves; corrections update them
- [ ] Memory page: view, edit, export, delete
- [ ] Search across past conversations

## ⏳ Phase 4: Tools and computer control
- [ ] Tool registry with permission levels (automatic / ask first / blocked)
- [ ] Approval prompts in the UI for consequential actions
- [ ] File search and organisation within approved folders
- [ ] Launch and close applications
- [ ] Execution log and audit trail; timeouts and limits
- [ ] Defences against instructions embedded in web pages and documents

## ⏳ Phase 5: Research and productivity
- [ ] Web search and page reading with cited sources
- [ ] Reminders and task list
- [ ] Optional calendar and email (official APIs; approval before sending)
- [ ] Study tools: maths rendering (LaTeX), worked solutions, revision planning

## ⏳ Phase 6: Advanced agent
- [ ] Multi-step planning with visible task progress
- [ ] Persistent tasks that survive restarts
- [ ] Error recovery and approval checkpoints

## ⏳ Phase 7: Cross-platform
- [ ] Login and authentication
- [ ] Secure remote access (encrypted tunnel, no open ports)
- [ ] Installable app (PWA) on iPhone and iPad
- [ ] Sync of conversations and memory

## ⏳ Phase 8: Long-term evolution
Better model selection, cost and performance tuning, more integrations, refined voice.

## Small improvements backlog
- LaTeX maths rendering (KaTeX, bundled locally), useful for study
- Regenerate or edit-and-resend a message
- Export a conversation to Markdown
- Show rate-limit usage from provider response headers
