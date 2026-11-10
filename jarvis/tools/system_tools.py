"""Tools that act on this computer: open apps and links, report system status.

Opening apps on Windows uses the Start menu's own app list (`Get-StartApps`),
which covers both classic programs and Store apps, and launches through the
shell's AppsFolder, the same route the Start menu takes. Other systems get a
simple fallback so the code can be developed and tested anywhere.
"""

from __future__ import annotations

import asyncio
import difflib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import webbrowser
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import psutil

from jarvis.tools.base import RISK_ACT, RISK_READ, Tool, ToolContext, ToolError, ToolResult, obj

# Things people ask for that aren't Start-menu entries. Opened through the shell.
WINDOWS_ALIASES = {
    "file explorer": "explorer.exe",
    "explorer": "explorer.exe",
    "files": "explorer.exe",
    "settings": "ms-settings:",
    "windows settings": "ms-settings:",
    "task manager": "taskmgr.exe",
    "control panel": "control.exe",
}


class AppLauncher:
    """Finds and starts installed applications. Subclassed per operating system."""

    backend = "none"
    confirm_seconds = 3.0  # how long to watch for a new process after launching

    def list_apps(self) -> list[dict[str, str]]:
        return []

    def find(self, name: str) -> tuple[dict[str, str] | None, list[str]]:
        """Best match for a spoken/typed app name, plus near misses to suggest."""
        wanted = " ".join(name.lower().split())
        apps = self.list_apps()
        by_name = {app["name"].lower(): app for app in apps}
        if wanted in by_name:
            return by_name[wanted], []
        starts = sorted((n for n in by_name if n.startswith(wanted)), key=len)
        contains = sorted((n for n in by_name if wanted in n), key=len)
        close = difflib.get_close_matches(wanted, list(by_name), n=4, cutoff=0.72)
        ranked = list(dict.fromkeys(starts + contains + close))
        if ranked:
            return by_name[ranked[0]], [by_name[n]["name"] for n in ranked[1:4]]
        loose = difflib.get_close_matches(wanted, list(by_name), n=3, cutoff=0.5)
        return None, [by_name[n]["name"] for n in loose]

    def launch(self, app: dict[str, str]) -> None:
        raise ToolError("Opening apps isn't supported on this operating system.")


class WindowsLauncher(AppLauncher):
    backend = "Windows Start menu"
    _CACHE_SECONDS = 300

    def __init__(self) -> None:
        self._apps: list[dict[str, str]] = []
        self._loaded = 0.0

    def list_apps(self) -> list[dict[str, str]]:
        if self._apps and time.monotonic() - self._loaded < self._CACHE_SECONDS:
            return self._apps
        command = (
            "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
            "Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress"
        )
        try:
            done = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                capture_output=True,
                timeout=25,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            data = json.loads(done.stdout.decode("utf-8", errors="replace") or "[]")
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            raise ToolError(f"Couldn't read the list of installed apps ({type(exc).__name__}).") from exc
        if isinstance(data, dict):
            data = [data]
        apps = [
            {"name": str(item["Name"]), "id": str(item["AppID"])}
            for item in data
            if isinstance(item, dict) and item.get("Name") and item.get("AppID")
        ]
        apps += [{"name": alias.title(), "id": target, "direct": "1"} for alias, target in WINDOWS_ALIASES.items()]
        self._apps, self._loaded = apps, time.monotonic()
        return apps

    def launch(self, app: dict[str, str]) -> None:
        target = app["id"] if app.get("direct") else f"shell:AppsFolder\\{app['id']}"
        try:
            os.startfile(target)  # type: ignore[attr-defined]  # Windows only
        except OSError:
            try:  # second route: let Explorer resolve it
                subprocess.Popen(["explorer.exe", target])
            except OSError as exc:
                raise ToolError(f"Windows refused to open {app['name']}: {exc.strerror or exc}") from exc


class PathLauncher(AppLauncher):
    """Fallback for macOS and Linux: programs found on PATH (and `open -a` on macOS)."""

    backend = "programs on PATH"

    def find(self, name: str) -> tuple[dict[str, str] | None, list[str]]:
        program = shutil.which(name) or shutil.which(name.lower().replace(" ", "-"))
        if program:
            return {"name": name, "id": program}, []
        if sys.platform == "darwin":
            return {"name": name, "id": name, "mac": "1"}, []
        return None, []

    def launch(self, app: dict[str, str]) -> None:
        command = ["open", "-a", app["id"]] if app.get("mac") else [app["id"]]
        try:
            subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError as exc:
            raise ToolError(f"Couldn't start {app['name']}: {exc.strerror or exc}") from exc


def default_launcher() -> AppLauncher:
    return WindowsLauncher() if sys.platform == "win32" else PathLauncher()


def _process_names() -> set[str]:
    names: set[str] = set()
    for proc in psutil.process_iter(["name"]):
        try:
            if proc.info["name"]:
                names.add(proc.info["name"].lower())
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return names


_GENERIC_WORDS = {"microsoft", "windows", "app", "exe", "the", "and", "for", "desktop", "store"}


def _name_tokens(app: dict[str, str]) -> set[str]:
    """Distinctive words from an app's name and ID, used to recognise its process."""
    words = re.findall(r"[a-z0-9]{3,}", f"{app['name']} {app['id']}".lower())
    return {word for word in words if word not in _GENERIC_WORDS}


def _matching(process_names: set[str], tokens: set[str]) -> list[str]:
    return sorted(name for name in process_names if any(token in re.sub(r"[^a-z0-9]", "", name) for token in tokens))


async def open_app(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    launcher: AppLauncher = ctx.services["launcher"]
    name = args["name"]
    app, suggestions = await asyncio.to_thread(launcher.find, name)
    if app is None:
        hint = f" Closest installed apps: {', '.join(suggestions)}." if suggestions else ""
        raise ToolError(f"No installed app matches '{name}'.{hint}")

    tokens = _name_tokens(app)
    before = await asyncio.to_thread(_process_names)
    already = _matching(before, tokens)
    await asyncio.to_thread(launcher.launch, app)
    # Confirm independently: did a process belonging to this app appear?
    started: list[str] = []
    for _ in range(int(launcher.confirm_seconds / 0.5)):
        await asyncio.sleep(0.5)
        started = _matching(await asyncio.to_thread(_process_names) - before, tokens)
        if started:
            break
    if started:
        return ToolResult(True, f"Opened {app['name']}. Confirmed: {started[0]} is now running.", summary=f"Opened {app['name']}")
    if already:
        return ToolResult(
            True,
            f"{app['name']} was already running ({already[0]}). The system has been asked to bring it to the front.",
            summary=f"{app['name']} was already open; asked to bring it forward",
        )
    return ToolResult(
        True,
        f"Asked the system to open {app['name']} and it accepted the request, but no matching new process "
        "appeared within a few seconds, so this could not be confirmed. Tell the user it should be opening.",
        summary=f"Asked to open {app['name']} (not confirmed)",
    )


async def open_url(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    url = args["url"]
    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ToolError("Only http and https web addresses can be opened.")
    opener = ctx.services.get("open_url") or webbrowser.open
    if not await asyncio.to_thread(opener, url):
        raise ToolError("The system has no web browser available to open that.")
    return ToolResult(True, f"Opened {url} in the default browser.", summary=f"Opened {parsed.netloc}")


def _gb(value: float) -> str:
    return f"{value / 1024**3:.1f} GB"


def system_snapshot() -> dict[str, Any]:
    memory = psutil.virtual_memory()
    disks = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except OSError:
            continue
        disks.append({"drive": part.mountpoint, "free": usage.free, "total": usage.total})
    battery = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    return {
        "os": f"{platform.system()} {platform.release()}",
        "cpu_percent": psutil.cpu_percent(interval=0.3),
        "cpu_cores": psutil.cpu_count(logical=False) or psutil.cpu_count() or 0,
        "memory_used": memory.used,
        "memory_total": memory.total,
        "memory_percent": memory.percent,
        "disks": disks[:6],
        "battery": None if battery is None else {"percent": round(battery.percent), "plugged": bool(battery.power_plugged)},
        "boot_time": datetime.fromtimestamp(psutil.boot_time()).astimezone().isoformat(timespec="seconds"),
    }


async def get_system_info(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    info = await asyncio.to_thread(system_snapshot)
    lines = [
        f"System: {info['os']}",
        f"CPU: {info['cpu_percent']:.0f}% in use ({info['cpu_cores']} cores)",
        f"Memory: {_gb(info['memory_used'])} of {_gb(info['memory_total'])} in use ({info['memory_percent']:.0f}%)",
    ]
    lines += [f"Disk {disk['drive']}: {_gb(disk['free'])} free of {_gb(disk['total'])}" for disk in info["disks"]]
    if info["battery"]:
        state = "plugged in" if info["battery"]["plugged"] else "on battery"
        lines.append(f"Battery: {info['battery']['percent']}% ({state})")
    else:
        lines.append("Battery: none detected")
    return ToolResult(True, "\n".join(lines), summary="Read system status", data={"system": info})


TOOLS = [
    Tool(
        name="open_app",
        group="computer",
        label="Open an app",
        description="Open an installed application on the user's computer by name, e.g. 'Spotify' or 'Notepad'.",
        parameters=obj({"name": {"type": "string", "description": "The app's name.", "maxLength": 80}}, ["name"]),
        risk=RISK_ACT,
        handler=open_app,
        describe=lambda a: f"Open {a.get('name', 'an app')}",
        timeout=40,
    ),
    Tool(
        name="open_url",
        group="computer",
        label="Open a web page",
        description="Open a web address in the user's default browser. This shows the page to the user; you cannot read it.",
        parameters=obj({"url": {"type": "string", "description": "Full address, e.g. https://www.bom.gov.au", "maxLength": 500}}, ["url"]),
        risk=RISK_ACT,
        handler=open_url,
        describe=lambda a: f"Open {a.get('url', 'a web page')}",
        timeout=15,
    ),
    Tool(
        name="get_system_info",
        group="computer",
        label="Check system status",
        description="Read this computer's current status: CPU and memory use, free disk space, battery.",
        parameters=obj({}),
        risk=RISK_READ,
        handler=get_system_info,
        describe=lambda a: "Check system status",
        timeout=15,
    ),
]
