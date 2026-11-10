"""Real app with an isolated, cross-platform launcher for browser checks."""
import os
import subprocess
import sys

import uvicorn

from jarvis.config import Settings
from jarvis.runtime import Runtime
from jarvis.server import create_app
from jarvis.tools.system_tools import AppLauncher


class MarkerLauncher(AppLauncher):
    backend = "isolated browser-test launcher"
    confirm_seconds = 0

    def list_apps(self):
        return [{"name": "e2e-marker-app", "id": "e2e-marker-app"}]

    def launch(self, app):
        subprocess.run(
            [sys.executable, "-c", "from pathlib import Path; import sys; Path(sys.argv[1]).write_text('launched')", os.environ["JARVIS_E2E_MARKER"]],
            check=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )


if __name__ == "__main__":
    runtime = Runtime(Settings.from_env(), launcher=MarkerLauncher())
    uvicorn.run(create_app(runtime=runtime), host="127.0.0.1", port=8765, log_level="warning")
