# JARVIS 1.0 assessment

Written 10 November 2026 from a direct inspection of the v0.1.0 code on `main`
(commit `dd7ac63`): 3,616 lines across 40 files, 35 passing tests.

## Verdict

Version 0.1 was a chat window connected to a language model. It was tidy and
tested, and nothing in it was faked, but it had none of the things that make an
assistant an assistant: it could not act, it remembered nothing between
conversations, and its personality was a paragraph of adjectives. Every message
went to the model with no knowledge of who was asking. That is why it felt like
a prototype.

## What it actually did

| Area | State in 0.1 | Evidence |
|---|---|---|
| Text chat with streaming | Worked | `chat.py`, `server.py`; 35 tests; browser run |
| Conversations saved across restarts | Worked | `storage.py`; restart test |
| Fallback between models | Worked, basic | `llm/router.py` |
| Rename, delete, stop | Worked | `web/app.js` |
| Markdown display | Worked, limited | hand-written `web/markdown.js` |
| A real reply from Groq | **Never verified** | the build sandbox cannot reach Groq |

Nothing was simulated or hard-coded to look functional. The only stand-in was
the `fake:` model, which is clearly labelled as a test device.

## Problems, by priority

### Critical

1. **No memory of the user.** Each conversation started from nothing. The only
   "memory" was the recent messages of the current conversation.
2. **No ability to act.** There was no tool calling at all. The model layer
   could only pass text back and forth, so JARVIS could not open an app, save a
   fact or look anything up. The system prompt even had to tell it to refuse.
3. **Personality by adjective.** The persona was a short list of traits with no
   examples, no situational guidance and no way for the user to tune or correct
   it. Models follow examples far better than adjectives, so the voice was
   generic.
4. **Never tested against the real provider.** No request had ever reached
   Groq. The default fallback model (`llama-3.1-8b-instant`) no longer appears
   in Groq's published limits, so the fallback may have been dead on arrival.
5. **Unprotected local API (latent).** Any web page open in another browser tab
   could call `http://127.0.0.1:8000/api/...`. Harmless while the API could
   only chat, but a serious hole the moment JARVIS can act on the computer.

### High

6. **Rate limits handled blindly.** A 429 simply failed over or errored. The
   provider's "retry after" time and remaining-allowance headers were ignored,
   and there was no usage tracking, so the user could not see how much of the
   free allowance was left.
7. **Request size ignored.** With 4,096 tokens reserved for output and up to
   12,000 characters of history, a long conversation could exceed the free
   tier's 8,000 tokens-per-minute limit and fail with no recovery.
8. **Long conversations silently forgot their beginning.** Messages beyond the
   history budget were dropped with no summary.
9. **Setup required editing a hidden text file.** The API key had to be pasted
   into `.env` in Notepad. No first-run guidance in the app.
10. **No maths rendering.** For a student using it for maths, chemistry and
    accounting, formulas appeared as raw LaTeX.

### Medium

11. **Hand-written Markdown parser.** 174 lines covering a subset of Markdown;
    no syntax highlighting; edge cases (nested lists, tables with inline code)
    were fragile.
12. **Settings could not be changed in the app.** Name, model order and
    everything else lived in `.env` and needed a restart.
13. **No way to correct a reply.** No regenerate, no edit-and-resend.
14. **No search** across conversations.
15. **Interface read as a tutorial project.** One accent colour on near-black,
    monospace labels, system fonts, a single screen.
16. **No record of what the model in use was doing or costing.**

### Low

17. Reasoning effort fixed in `.env`.
18. Console window stays open (still true; acceptable for now).
19. No export of conversations.

## What was worth keeping

- The single-process FastAPI + SQLite shape, and the migration system.
- The OpenAI-compatible provider client (extended, not replaced).
- The ordered-fallback router (extended).
- The streaming protocol to the browser (extended with tool and approval events).
- The Windows setup scripts and uv-based install.
- The practice of testing in a real browser before shipping.

## Highest-impact improvements, in order

1. A real long-term memory that feeds every reply and learns on its own.
2. A properly written, tunable, teachable personality.
3. An agent core: tool calling with permissions, approvals and an action log
   (memory itself depends on this).
4. Rate-limit awareness, usage tracking and request-size recovery, so the free
   tier is dependable.
5. Protecting the local API before any action tools ship.
6. A redesigned interface with first-run setup, maths, and screens for memory,
   activity and settings.

These six are what version 2.0 delivers. Voice, web research and file tools
follow on the framework 2.0 puts in place (see [ROADMAP](ROADMAP.md)).
