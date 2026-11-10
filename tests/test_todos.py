from __future__ import annotations

import asyncio

import pytest

from jarvis.tools.base import ToolContext
from tests.conftest import call, run_turn, scripted_runtime, text


def test_todo_storage_and_status_changes(runtime):
    first = runtime.store.create_todo("Buy milk", "Use the corner shop", due_at="2026-11-11T08:30:00+10:00")
    second = runtime.store.create_todo("Read the docs")
    assert [item["title"] for item in runtime.store.list_todos()] == ["Buy milk", "Read the docs"]
    assert first["due_at"] == "2026-11-10T22:30:00Z"
    assert runtime.store.update_todo_status(first["id"], "completed")["completed_at"]
    assert runtime.store.list_todos("pending") == [second]
    assert runtime.store.list_todos("completed")[0]["id"] == first["id"]
    assert runtime.store.update_todo_status(first["id"], "pending")["completed_at"] is None
    with pytest.raises(ValueError, match="valid ISO"):
        runtime.store.create_todo("Bad date", due_at="tomorrow")
    deleted = runtime.store.delete_todo(second["id"])
    assert deleted["title"] == "Read the docs"
    assert [item["title"] for item in runtime.store.list_todos("all")] == ["Buy milk"]
    edited = runtime.store.update_todo(first["id"], title="Buy oat milk", details="Ask for the unsweetened one")
    assert edited["title"] == "Buy oat milk" and edited["details"].startswith("Ask for")


def test_todo_tools_use_normal_agent_path(settings):
    runtime, provider = scripted_runtime(
        settings,
        [call("add_todo", title="Buy milk", details="Corner shop")],
        [call("list_todos")],
        [call("change_todo", id=1, status="completed")],
        [text("Done.")],
    )
    run_turn(runtime, "Add a to-do")
    run_turn(runtime, "List my to-dos")
    run_turn(runtime, "Complete to-do 1")
    todos = runtime.store.list_todos("all")
    assert todos[0]["status"] == "completed"
    assert len(provider.calls) == 6


def test_delete_todo_is_sensitive(runtime):
    tool = runtime.registry.get("delete_todo")
    assert tool.risk == "sensitive"


def test_edit_todo_is_an_action(runtime):
    assert runtime.registry.get("edit_todo").risk == "act"
    todo = runtime.store.create_todo("Old title")
    updated = runtime.store.update_todo(todo["id"], due_at="2026-12-01T10:00:00Z")
    assert updated["due_at"] == "2026-12-01T10:00:00Z"


def test_list_todos_labels_overdue_items(runtime):
    runtime.store.create_todo("Missed deadline", due_at="2020-01-01T00:00:00Z")
    tool = runtime.registry.get("list_todos")
    result = asyncio.run(tool.handler({"status": "pending"}, ToolContext(None, "test", runtime.services)))
    assert "OVERDUE" in result.text
