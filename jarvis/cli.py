"""Command line entry point.

  uv run jarvis            start JARVIS and open it in your browser
  uv run jarvis serve      same, with options (--port, --no-browser)
  uv run jarvis check      test each configured model and API key
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import threading
import time
import webbrowser

from jarvis import __version__
from jarvis.config import Settings
from jarvis.llm import ChatMessage, LLMError
from jarvis.llm.router import build_provider


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%I:%M:%S %p",
    )


def serve(settings: Settings, host: str | None, port: int | None, open_browser: bool) -> None:
    import uvicorn

    from jarvis.server import create_app

    host = host or settings.host
    port = port or settings.port
    app = create_app(settings)
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{port}"

    print(f"\n  J.A.R.V.I.S. v{__version__}")
    print(f"  Online at {url}   (press Ctrl+C to shut down)\n")
    models = app.state.router.labels
    print(f"  Models: {', '.join(models) if models else 'NONE CONFIGURED'}")
    for reason in app.state.router.skipped:
        print(f"  Skipped: {reason}")
    if host not in ("127.0.0.1", "localhost", "::1"):
        print("\n  WARNING: listening beyond this computer, and JARVIS has no login yet.")
        print("  Anyone on your network could use it. Set JARVIS_HOST=127.0.0.1 unless you're sure.\n")

    if open_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=host, port=port, log_level="warning")


async def check(settings: Settings) -> int:
    """Send a tiny prompt to each configured model and report what works."""
    print(f"Checking {len(settings.models)} configured model(s)...\n")
    working = 0
    for spec in settings.models:
        print(f"* {spec.label}")
        try:
            provider = build_provider(spec, settings)
        except ValueError as exc:
            print(f"    SKIPPED  {exc}\n")
            continue
        messages = [
            ChatMessage("system", "You are a connectivity test. Reply with exactly: Systems online."),
            ChatMessage("user", "Status check."),
        ]
        started = time.perf_counter()
        try:
            reply = "".join([chunk async for chunk in provider.stream_chat(messages)]).strip()
        except LLMError as exc:
            print(f"    FAILED   {exc}")
            if exc.status == 404:
                try:
                    models = await provider.list_models()
                    print(f"    Models available from {spec.provider}:")
                    for model_id in models[:40]:
                        print(f"      {model_id}")
                except LLMError:
                    pass
            print()
            continue
        elapsed = time.perf_counter() - started
        if reply:
            working += 1
            print(f"    OK       {elapsed:.1f}s  reply: {reply[:80]!r}\n")
        else:
            print("    FAILED   the model returned an empty reply.\n")

    if working:
        print(f"{working} of {len(settings.models)} model(s) working. JARVIS is ready: run start.bat")
        return 0
    print("No working models. Check the API key(s) in .env and see README > Troubleshooting.")
    return 1


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="jarvis", description="JARVIS personal AI assistant")
    parser.add_argument("--version", action="version", version=f"jarvis {__version__}")
    sub = parser.add_subparsers(dest="command")
    serve_parser = sub.add_parser("serve", help="start the JARVIS server (default)")
    serve_parser.add_argument("--host", help="interface to bind (default from .env, 127.0.0.1)")
    serve_parser.add_argument("--port", type=int, help="port (default from .env, 8000)")
    serve_parser.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    sub.add_parser("check", help="test each configured model and API key")
    args = parser.parse_args(argv)

    try:
        settings = Settings.from_env()
    except ValueError as exc:
        print(f"Configuration error: {exc}")
        sys.exit(2)

    if args.command == "check":
        sys.exit(asyncio.run(check(settings)))

    _setup_logging()
    serve(
        settings,
        host=getattr(args, "host", None),
        port=getattr(args, "port", None),
        open_browser=settings.open_browser and not getattr(args, "no_browser", False),
    )
