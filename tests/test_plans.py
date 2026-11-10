from __future__ import annotations

import asyncio
import json

import pytest

from jarvis.tools.base import ToolContext
from jarvis.llm.base import ChatMessage
from jarvis.llm.fake import scripted_reply
from tests.conftest import call, run_turn, scripted_runtime, text


def test_plan_storage_survives_listing(runtime):
    plan = runtime.store.create_plan("Revise chemistry", ["Review notes", "Do practice questions"])
    assert plan["status"] == "active"
    assert [step["position"] for step in plan["steps"]] == [1, 2]
    listed = runtime.store.list_plans()
    assert listed[0]["title"] == "Revise chemistry"
    assert [step["title"] for step in listed[0]["steps"]] == ["Review notes", "Do practice questions"]
    assert listed[0]["next_step"]["title"] == "Review notes"
    assert runtime.store.list_plans("completed") == []
    assert runtime.store.get_plan(plan["id"])["next_step"]["position"] == 1
    completed = runtime.store.update_plan_step(plan["id"], 1, "completed")
    assert completed["status"] == "active"
    completed = runtime.store.update_plan_step(plan["id"], 2, "completed")
    assert completed["status"] == "completed"
    reopened = runtime.store.update_plan_step(plan["id"], 1, "pending")
    assert reopened["status"] == "active"
    cancelled = runtime.store.update_plan_status(plan["id"], "cancelled")
    assert cancelled["status"] == "cancelled"
    reopened = runtime.store.update_plan_status(plan["id"], "active")
    assert reopened["status"] == "active"


def test_plan_storage_validates_steps(runtime):
    with pytest.raises(ValueError, match="at least one"):
        runtime.store.create_plan("Empty", [])
    with pytest.raises(ValueError, match="needs a title"):
        runtime.store.create_plan(" ", ["Step"])


def test_plan_tools_use_normal_agent_path(settings):
    runtime, provider = scripted_runtime(
        settings,
        [call("create_plan", title="Revise chemistry", steps=["Review notes", "Do questions"])],
        [call("list_plans")],
        [text("Plan saved.")],
    )
    run_turn(runtime, "Create a chemistry plan")
    run_turn(runtime, "List my plans")
    result = asyncio.run(
        runtime.registry.get("list_plans").handler(
            {"status": "active"}, ToolContext(None, "test", runtime.services)
        )
    )
    assert "Revise chemistry" in result.text
    assert "Review notes" in result.text
    assert "Next: 1. Review notes" in result.text
    assert len(provider.calls) == 4


def test_fake_model_understands_plan_phrasing():
    messages = [ChatMessage("user", "Create a plan: revise chemistry with steps review notes; do questions")]
    reply, calls = scripted_reply(messages, [{"function": {"name": "create_plan"}}])
    assert calls[0].name == "create_plan"
    assert json.loads(calls[0].arguments)["steps"] == ["review notes", "do questions"]
    reply, calls = scripted_reply([ChatMessage("user", "list plans")], [{"function": {"name": "list_plans"}}])
    assert calls[0].name == "list_plans"
    reply, calls = scripted_reply(
        [ChatMessage("user", "complete plan 1 step 2")],
        [{"function": {"name": "change_plan_step"}}],
    )
    assert calls[0].name == "change_plan_step"
    reply, calls = scripted_reply(
        [ChatMessage("user", "resume plan 1")],
        [{"function": {"name": "resume_plan"}}],
    )
    assert calls[0].name == "resume_plan"
    reply, calls = scripted_reply(
        [ChatMessage("user", "cancel plan 1")],
        [{"function": {"name": "change_plan_status"}}],
    )
    assert calls[0].name == "change_plan_status"
