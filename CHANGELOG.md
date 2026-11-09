# Changelog

## 0.1.0 (2026-11-09): Phase 1, text chat foundation
- Web chat interface with streaming replies, Markdown/code/table rendering, copy buttons and Stop
- JARVIS persona with honest capability statement, local date and time, 12-hour times
- Persistent conversations in SQLite (create, list, open, rename, delete) with schema migrations
- Model layer: any OpenAI-compatible API (Groq, Gemini, OpenRouter, Ollama, custom) with ordered fallback
- `jarvis check` command to test API keys and list available models
- Offline `fake:demo` / `fake:echo` models
- Windows `setup.bat`, `start.bat`, `check.bat`; uv-managed Python 3.12
- 35 automated tests
