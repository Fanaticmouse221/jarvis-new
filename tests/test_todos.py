from __future__ import annotations

import pytest

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
