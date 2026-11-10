"""Command line entry point.

  uv run jarvis            start JARVIS and open its window
  uv run jarvis serve      same, with options (--port, --no-browser)
  uv run jarvis check      test each configured model and API key
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import shutil
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

from jarvis import __version__
from jarvis.config import Settings


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%I:%M:%S %p",
    )


def find_edge() -> str | None:
    """Microsoft Edge ships with Windows and can show a site as its own app window."""
    found = shutil.which("msedge")
    if found:
        return found
    for root in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if root:
            candidate = Path(root) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if candidate.exists():
                return str(candidate)
    return None


def open_window(url: str, mode: str) -> None:
    """Show the interface: in its own window if possible, otherwise the default browser."""
    if mode == "none":
        return
    if mode == "app" and sys.platform == "win32":
        edge = find_edge()
        if edge:
            try:
                subprocess.Popen([edge, f"--app={url}", "--window-size=1280,860"])
                return
            except OSError:
                pass
    webbrowser.open(url)


def serve(settings: Settings, host: str | None, port: int | None, open_browser: bool) -> None:
    import uvicorn

    from jarvis.server import create_app

    host = host or settings.host
    port = port or settings.port
    app = create_app(settings)
    runtime = app.state.runtime
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{port}"

    print(f"\n  J.A.R.V.I.S. v{__version__}")
    print(f"  Online at {url}   (close this window, or press Ctrl+C, to shut down)\n")
    models = runtime.router.labels
    print(f"  Models: {', '.join(models) if models else 'none yet. Add a key in the app.'}")
    counts = runtime.store.counts()
    print(f"  Memory: {counts['memories']} memories, {counts['conversations']} conversations")
    if host not in ("127.0.0.1", "localhost", "::1"):
        print("\n  WARNING: listening beyond this computer. Anyone who can reach this address and")
        print("  obtain the page can use JARVIS. Set JARVIS_HOST=127.0.0.1 unless you're sure.\n")

    if open_browser:
        threading.Timer(1.2, open_window, args=(url, settings.window)).start()
    uvicorn.run(app, host=host, port=port, log_level="warning")


async def check(settings: Settings) -> int:
    """Send a tiny prompt to each configured model and report what works."""
    from jarvis.runtime import Runtime

    runtime = Runtime(settings)
    results = await runtime.check_models()
    if not results:
        print("No models are configured. Start JARVIS and add a Groq key in Settings.")
        return 1
    print(f"Checking {len(results)} model(s)...\n")
    for result in results:
        mark = "OK    " if result["ok"] else "FAILED"
        print(f"* {result['model']}\n    {mark}  {result['seconds']:.1f}s  {result['detail']}\n")
    working = sum(1 for result in results if result["ok"])
    if working:
        print(f"{working} of {len(results)} model(s) working. JARVIS is ready: run start.bat")
        return 0
    print("No working models. Check the API key in Settings (or .env) and see README > Troubleshooting.")
    return 1


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="jarvis", description="JARVIS personal AI assistant")
    parser.add_argument("--version", action="version", version=f"jarvis {__version__}")
    sub = parser.add_subparsers(dest="command")
    serve_parser = sub.add_parser("serve", help="start JARVIS (default)")
    serve_parser.add_argument("--host", help="interface to bind (default from .env, 127.0.0.1)")
    serve_parser.add_argument("--port", type=int, help="port (default from .env, 8000)")
    serve_parser.add_argument("--no-browser", action="store_true", help="don't open a window")
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
