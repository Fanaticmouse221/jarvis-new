# Working on JARVIS

Personal AI assistant for Jack. Read `docs/ARCHITECTURE.md`, `docs/DECISIONS.md` and `docs/ROADMAP.md` before significant changes.

## Ground rules
- **Free first.** Never add a paid service, or anything that could incur charges, without Jack's explicit approval. Verify current pricing and limits before recommending a service.
- **Ask before** major architectural changes, sensitive permissions, or destructive operations.
- **Never commit secrets.** API keys live only in `.env` (git-ignored). Update `.env.example` when adding settings.
- **Target platform:** Windows 11 (Jack's PC: Ryzen 5 5625U, integrated graphics, 16 GB RAM, limited disk). Keep code compatible with Python 3.10+; uv runs 3.12.
- **Honesty:** keep the capability list in `jarvis/persona.py` in step with what's actually implemented.
- **Times** shown to Jack are 12-hour format (e.g. 6:52 PM).
- Keep it simple: one process, SQLite, no frontend build step, unless a decision in `docs/DECISIONS.md` changes that.

## Commands
```bash
uv sync                    # install dependencies
uv run pytest -q           # all tests must pass before committing
uv run jarvis serve --no-browser --port 8765    # run locally
JARVIS_MODELS=fake:demo uv run jarvis serve     # UI without an API key
```

## When finishing a piece of work
1. Tests pass (add tests for new behaviour).
2. Update `CHANGELOG.md`, tick items in `docs/ROADMAP.md`, and add a `docs/DECISIONS.md` entry for any new technology choice.
3. Tell Jack exactly how to pull, set up and test the change on Windows.
