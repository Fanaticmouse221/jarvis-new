# Working on JARVIS

Personal AI assistant for Jack. **Start with `HANDOFF.md`**: it says where the project stands and what to do next. Then read `docs/ARCHITECTURE.md`, `docs/DECISIONS.md` and `docs/ROADMAP.md` before significant changes.

These instructions are for any AI assistant working on this repository. `AGENTS.md` and `CLAUDE.md` hold the same text; change both together.

## What matters most
**Memory and personality are the product.** Anything that weakens either (a prompt change that flattens the voice, a shortcut that drops memories from context) is a regression even if tests pass.

## Ground rules
- **Free first.** Never add a paid service, or anything that could incur charges, without Jack's explicit approval. Verify current pricing and limits before recommending a service.
- **Ask before** major architectural changes, sensitive permissions, or destructive operations.
- **Never fake a capability.** Tools must do the real thing and report the real outcome. The capability list in `jarvis/persona.py` is generated from enabled tools; keep `MISSING_ALWAYS` in step with what is not built.
- **Status claims need evidence.** In `docs/ROADMAP.md`, "tested and working" means automated tests plus a browser run. Anything only checked against the mock, or Windows-only, is "built, needs a real-world check".
- **Never commit secrets.** API keys live only in `.env` (git-ignored). Update `.env.example` when adding settings.
- **Target platform:** Windows 11 (Jack's PC: Ryzen 5 5625U, integrated graphics, 16 GB RAM, limited disk). Keep code compatible with Python 3.10+; uv runs 3.12. The build sandbox is Linux and cannot reach Groq, so Windows-only and live-provider paths can't be run here.
- **Groq's free tier is tight** (8,000 tokens a minute per model). Keep prompts, tool descriptions and tool results compact; see D21.
- **Times** shown to Jack are 12-hour format (e.g. 6:52 PM). British/Australian spelling.
- Keep it simple: one process, SQLite, no frontend build step, no agent framework, unless a decision in `docs/DECISIONS.md` changes that.
- New tools go in `jarvis/tools/` with a risk level; anything that returns outside content must set `untrusted_output=True`.

## Keep the handoff alive
Jack may continue this project in a different AI at any time. Before every commit, update `HANDOFF.md` (current state, ticked boxes, what to do next) and add an entry at the top of `docs/WORKLOG.md` (what changed, what was verified and how, what is unverified). Commit small and push often, so nothing lives only in one session.

## Commands
```bash
uv sync                                         # install dependencies
uv run pytest -q                                # all tests must pass before committing
uv run jarvis serve --no-browser --port 8765    # run locally
JARVIS_MODELS=fake:agent uv run jarvis serve    # scripted demo brain, no key needed
python tests/e2e/run_e2e.py                     # full browser run (Playwright + Chrome)
```

## When finishing a piece of work
1. Tests pass (add tests for new behaviour) and the browser run passes; look at its screenshots.
2. Update `CHANGELOG.md`, the status table in `docs/ROADMAP.md`, `HANDOFF.md`, `docs/WORKLOG.md`, and add a `docs/DECISIONS.md` entry for any new technology choice.
3. Tell Jack exactly how to update and what to try, and say plainly what could not be verified here.
