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

---

## Version 2.0 (2026-11-10)

### D11. Memory and personality are the centre of the product
**Why:** Jack's direction. An assistant that knows who it works for and sounds
like itself is the difference between JARVIS and a chat window. Every other
2.0 decision serves these two.

### D12. Memory in SQLite with full-text search; no embeddings yet
**Why:** A personal memory is hundreds of short facts, not millions. While it
all fits in about 1,800 characters, everything is sent with every message, so
retrieval cannot miss. Beyond that, pinned items, FTS5 keyword matches and the
`recall` tool cover it. An embedding model would add a large download and a
heavy dependency for no measurable gain at this size, and could not be tested
in the build environment.
**Revisit if:** memory passes roughly 500 items, or keyword recall visibly misses things.

### D13. Two ways to learn: told and noticed
**Why:** Relying only on the model to call `remember` means things get missed.
So after each reply a second, cheap pass asks a model to extract durable facts
as JSON. To protect the free allowance it runs only when the message looks
personal, is skipped if `remember` was already used, and goes to the *last*
model in the list (on Groq each model has its own limit). Everything learned is
shown in the conversation with Undo, and logged.

### D14. Rolling summaries for long conversations
**Why:** The free tier's token limit means only recent history can be sent.
Rather than silently forgetting the start of a long conversation, dropped
messages are folded into a short summary that stays in the prompt.

### D15. Personality is one prompt builder with examples, dials and learned rules
**Why:** Models imitate examples much more faithfully than trait lists, so the
character is defined by rules plus a few original example exchanges. Three
dials (manner, humour, length) and standing instructions from memory let Jack
shape it without editing code. The example lines are written for this project.

### D16. A hand-written agent loop, no agent framework
**Why:** The loop is about 150 lines: ask, run tools, repeat. Writing it keeps
every step visible and testable, avoids a large dependency, and makes
approvals and the action log first-class instead of bolted on.

### D17. Three risk levels, per-tool permissions, approvals, and an outside-content rule
**Why:** "Read" runs, "act" runs unless Jack says ask, "sensitive" always asks.
Once a turn has read outside content, all actions in it need approval, which
blocks instructions hidden in web pages or files. Built now so the web and file
tools in 2.2 inherit it.

### D18. Protect the local API with a session token, host check and origin check
**Why:** JARVIS can now act on the computer. Without this, any web page open in
another tab could send it commands. The token is only ever given to JARVIS's
own page.

### D19. Keys are entered in the app and written to `.env`
**Why:** Editing a hidden file in Notepad was the worst part of 0.1 setup. The
app checks the key with the provider before saving. `.env` remains the single
place secrets live.

### D20. Front-end libraries are bundled, not loaded from a CDN
**Why:** marked (Markdown), DOMPurify (sanitising), KaTeX (maths) and
highlight.js (code), plus the Saira and IBM Plex fonts, live in `web/vendor`
(about 1 MB). JARVIS works offline for everything but the model, nothing is
fetched from third parties at run time, and there is still no build step.
This replaces the hand-written Markdown parser from 0.1.

### D21. Budget every request for Groq's free tier
**Why (checked 2026-11-10):** gpt-oss-120b and gpt-oss-20b each allow 30
requests a minute, 1,000 a day, 8,000 tokens a minute and 200,000 tokens a day.
So: output capped at 2,048 tokens, history at 6,000 characters, tool results at
3,000; a 413 "too large" is retried with less history; a 429 rests that model
for the time Groq states while the next one answers.
**Supersedes D7's fallback:** `llama-3.1-8b-instant` no longer appears in
Groq's published limits, so the default second model is now `openai/gpt-oss-20b`,
and when a key is added the list is built from what the account can actually use.
**Supersedes D8:** context is now 24 messages / 6,000 characters plus the summary.

### D22. Voice, web research and file tools wait for 2.1 and 2.2
**Why:** Doing memory and personality properly took priority. The tool
framework, permissions and outside-content rule they need are already in place.

### D23. Open in an app-style window through Microsoft Edge
**Why:** Edge ships with Windows and can show a site without browser chrome,
which makes JARVIS feel like a program rather than a tab. Falls back to the
default browser. Edge's built-in natural voices are also the best free option
for spoken replies in 2.1.
