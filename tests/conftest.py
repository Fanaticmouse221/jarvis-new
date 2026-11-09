from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jarvis.config import Settings, parse_model_list
from jarvis.llm import ModelRouter
from jarvis.server import create_app
from jarvis.storage import Store


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(models=parse_model_list("fake:echo"), db_path=tmp_path / "test.db", open_browser=False)


@pytest.fixture
def store(settings: Settings) -> Store:
    return Store(settings.db_path)


def make_client(settings: Settings, models: str = "fake:echo") -> TestClient:
    settings = Settings(models=parse_model_list(models), db_path=settings.db_path, open_browser=False)
    return TestClient(create_app(settings, router=ModelRouter.from_settings(settings)))


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return make_client(settings)


def parse_sse(text: str) -> list[dict]:
    """Turn a Server-Sent Events body into a list of event dicts."""
    events = []
    for block in text.strip().split("\n\n"):
        data = [line[5:].strip() for line in block.splitlines() if line.startswith("data:")]
        if data:
            events.append(json.loads("\n".join(data)))
    return events
