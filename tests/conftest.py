from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from jarvis.config import Settings, parse_model_list
from jarvis.llm import ModelRouter, StreamEvent, ToolCall
from jarvis.llm.fake import FakeProvider
from jarvis.runtime import Runtime
from jarvis.server import create_app
from jarvis.tools.system_tools import AppLauncher


class FakeLauncher(AppLauncher):
    """Stands in for the operating system's app list in tests."""

    backend = "test"
    confirm_seconds = 0.0

    def __init__(self) -> None:
        self.launched: list[str] = []
        self.closed: list[str] = []

    def list_apps(self) -> list[dict[str, str]]:
        return [{"name": name, "id": name.lower()} for name in ("Notepad", "Spotify", "Visual Studio Code", "Calculator")]

    def launch(self, app: dict[str, str]) -> None:
        self.launched.append(app["name"])

    def close(self, app: dict[str, str]) -> list[str]:
        self.closed.append(app["name"])
        return [app["name"].lower() + ".exe"]


def make_settings(tmp_path: Path, models: str = "fake:agent", **overrides: Any) -> Settings:
    return Settings(
        models=parse_model_list(models),
        db_path=tmp_path / "test.db",
        env_path=tmp_path / ".env",
        workspace=tmp_path / "workspace",
        open_browser=False,
        **overrides,
    )


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def runtime(settings: Settings) -> Runtime:
    return Runtime(settings, launcher=FakeLauncher())


def scripted_runtime(settings: Settings, *replies: list[StreamEvent], learn: bool = False) -> tuple[Runtime, FakeProvider]:
    """A runtime whose 'model' replays the given replies, one per model call.

    Background learning is off unless asked for, so it can't consume scripted replies.
    """
    provider = FakeProvider("script", script=[list(reply) for reply in replies])
    runtime = Runtime(settings, router=ModelRouter([provider]), launcher=FakeLauncher())
    runtime.update_prefs({"auto_learn": learn})
    return runtime, provider


def text(content: str) -> StreamEvent:
    return StreamEvent("text", text=content)


def call(tool: str, /, **arguments: Any) -> StreamEvent:
    return StreamEvent("tool_call", tool_call=ToolCall(f"call_{tool}_{len(arguments)}", tool, json.dumps(arguments)))


def run_turn(runtime: Runtime, message: str = "", conversation_id: str | None = None, **start: Any) -> tuple[str, list[dict[str, Any]]]:
    """Send one message through the agent and wait for background learning to finish."""

    async def go() -> tuple[str, list[dict[str, Any]]]:
        conversation = runtime.agent.start_turn(conversation_id, message, **start)
        events = [event async for event in runtime.agent.run_turn(conversation)]
        await runtime.wait_for_background()
        return conversation["id"], events

    return asyncio.run(go())


def steps(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [event["step"] for event in events if event["type"] == "tool_end"]


class Client(TestClient):
    """TestClient that presents the session token, as the real interface does."""

    def __init__(self, runtime: Runtime):
        super().__init__(create_app(runtime=runtime), headers={"X-Jarvis-Token": runtime.token})
        self.runtime = runtime


@pytest.fixture
def client(runtime: Runtime) -> Client:
    return Client(runtime)


def parse_sse(body: str) -> list[dict]:
    """Turn a Server-Sent Events body into a list of event dicts."""
    events = []
    for block in body.strip().split("\n\n"):
        data = [line[5:].strip() for line in block.splitlines() if line.startswith("data:")]
        if data:
            events.append(json.loads("\n".join(data)))
    return events
