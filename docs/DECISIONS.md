# Decision log

Each entry records what was decided, why, and what would make us revisit it.
Newest entries go at the bottom. Hardware context: AMD Ryzen 5 5625U laptop
(6 cores / 12 threads, Radeon integrated graphics, 0.5 GB dedicated VRAM),
16 GB RAM, Windows 11 Home, about 26 GB free disk.

---

### D1. Python + FastAPI for the backend (2026-11-09)
**Why:** Python has the strongest ecosystem for everything on the roadmap:
speech-to-text, text-to-speech, wake words, local models, automation. FastAPI is
small, fast, async (needed for streaming) and generates API docs automatically.
**Alternatives:** Node.js (weaker AI/audio ecosystem), Rust (slower to develop).
**Revisit if:** a component needs native performance; it can be added as a separate module.

### D2. A web interface as the single frontend (2026-11-09)
**Why:** One codebase runs on Windows now and on iPhone/iPad later through the
browser, and can be installed to the home screen as a PWA. It avoids building a
native iOS app, which needs a Mac and an Apple developer account.
**Revisit if:** iOS features such as background audio or widgets become essential;
a thin native shell could wrap the same backend.

### D3. Plain JavaScript with no build step (2026-11-09)
**Why:** Nothing to install or compile, and easy to read and modify. A framework
would add tooling without solving a current problem.
**Revisit if:** the UI grows to many interactive screens (likely around Phases 3 to 5).

### D4. SQLite for storage (2026-11-09)
**Why:** No server, one file that's easy to back up, transactional, built into
Python. Migrations are tracked with `PRAGMA user_version`.
**Revisit if:** multiple machines need to write concurrently (Phase 7 sync).

### D5. Cloud models first, local models optional (2026-11-09)
**Why:** This hardware has no discrete GPU. Local models would run on the CPU at
a few words per second, with much lower quality than free cloud models, and would
use scarce disk space. Free cloud tiers give fast, capable replies at no cost.
**Revisit if:** the hardware changes, or privacy needs require fully offline operation.
Ollama support is already built in as a fallback option.

### D6. One OpenAI-compatible client and an ordered fallback list (2026-11-09)
**Why:** Groq, Gemini, OpenRouter and Ollama all speak the same API, so one
client covers them and switching providers is a `.env` edit. Free tiers have rate
limits, so automatic fallback keeps JARVIS answering. Groq limits apply per model,
so a second Groq model doubles as extra capacity on the same key.
Implemented with `httpx` directly rather than a vendor SDK: fewer dependencies and
full control over streaming and error messages.

### D7. Groq as the primary provider (2026-11-09)
**Why (verified November 2026):** a standing free tier with no card required; it
doesn't train on API data; Zero Data Retention is available to all customers;
very fast. Default model `openai/gpt-oss-120b` (free tier: 30 requests/min,
1,000/day, 8,000 tokens/min, 200,000 tokens/day), with `llama-3.1-8b-instant`
as a fallback.
**Rejected:** Cerebras (no standing free tier since mid-2026; a trial needs a card).
**Optional:** Gemini (free tier trains on prompts, with possible human review, and
caps were cut in 2025 and 2026); OpenRouter (50 free requests/day).
**Revisit if:** Groq's free tier changes; `jarvis check` will show failures.

### D8. Context limited by message count and characters (2026-11-09)
**Why:** Groq's free tier allows about 8,000 tokens per minute for gpt-oss-120b.
The defaults (30 messages, 12,000 characters, about 3,000 tokens) leave room for
the reply. Long-term recall is the job of the Phase 3 memory system, not ever-larger prompts.

### D9. Localhost-only by default (2026-11-09)
**Why:** There is no authentication yet. Remote access (Phase 7) will come with a
login and an encrypted tunnel, never by opening a port to the internet.

### D10. uv for Python and dependency management (2026-11-09)
**Why:** Installs the correct Python version per project (3.12; the system's
Python 3.10 reached end of life in October 2026), uses a lockfile for
reproducible installs, and makes setup one command. The code stays compatible
with Python 3.10+ in case uv isn't used.
