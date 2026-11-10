import asyncio
import sqlite3

import pytest

from jarvis.persona import build_system_prompt
from jarvis.storage import MIGRATIONS, Store
from jarvis.tools import RISK_ACT, RISK_READ, RISK_SENSITIVE, Tool, ToolContext, ToolError, ToolResult
from jarvis.tools.base import obj, validate_args

from conftest import call, run_turn, scripted_runtime, steps, text


def test_v2_migration_preserves_data_and_adds_reminders(tmp_path):
    path = tmp_path / "v2.db"
    with sqlite3.connect(path) as conn:
        for migration in MIGRATIONS[:2]:
            conn.executescript(migration)
        conn.execute("PRAGMA user_version = 2")
        conn.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at, summary, summary_upto) "
            "VALUES ('old', 'Revision', '2026-11-09T08:00:00Z', '2026-11-09T08:00:00Z', 'Chemistry', 1)"
        )
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content, created_at) "
            "VALUES ('old', 'user', 'Remember chemistry', '2026-11-09T08:00:00Z')"
        )
    store = Store(path)
    old = store.get_conversation("old")
    assert old["source"] == "app" and old["summary"] == "Chemistry" and old["summary_upto"] == 1
    assert store.get_messages("old")[0]["content"] == "Remember chemistry"
    phone = store.create_conversation("Phone", source="telegram")
    assert store.get_conversation(phone["id"])["source"] == "telegram"
    assert {c["source"] for c in store.list_conversations()} == {"app", "telegram"}
    with store._connect() as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 6
        conn.execute(
            "INSERT INTO reminders (text, due_at, conversation_id, created_at) VALUES (?, ?, ?, ?)",
            ("Study", "2026-11-10T08:00:00Z", phone["id"], "2026-11-09T08:00:00Z"),
        )
    store.delete_conversation(phone["id"])
    with Store(path)._connect() as conn:
        reminder = dict(conn.execute("SELECT * FROM reminders").fetchone())
    assert reminder["status"] == "pending" and reminder["repeat"] == "none"
    assert reminder["conversation_id"] is None and reminder["sent_at"] is None
    with pytest.raises(ValueError, match="source"):
        store.create_conversation(source="outside")


def make_dynamic_tool(handler, risk_for):
    return Tool(
        "write_test", "computer", "Write", "Write a file", obj({"mode": {"type": "string"}}, ["mode"]),
        RISK_ACT, handler, lambda args: "Write a file", risk_for=risk_for,
    )


@pytest.mark.parametrize("mode,approval", [("create", None), ("overwrite", False), ("overwrite", True)])
def test_per_call_risk_controls_approval_and_log(settings, mode, approval):
    runtime, _ = scripted_runtime(settings, [call("write_test", mode=mode)], [text("Finished.")])
    calls = []

    async def write(args, ctx):
        calls.append(args["mode"])
        return ToolResult(True, "Written")

    runtime.registry.register(make_dynamic_tool(write, lambda args, ctx: RISK_SENSITIVE if args["mode"] == "overwrite" else RISK_ACT))
    runtime.update_prefs({"tool_policy": {"write_test": "allow"}})

    async def go():
        conversation = runtime.agent.start_turn(None, "Write this")
        events = []
        async for event in runtime.agent.run_turn(conversation):
            events.append(event)
            if event["type"] == "approval_required":
                assert approval is not None and not event["can_always"]
                assert calls == []
                runtime.approvals.resolve(event["id"], approval, always=True)
        return events

    events = asyncio.run(go())
    assert calls == ([mode] if approval is not False else [])
    risk = RISK_ACT if mode == "create" else RISK_SENSITIVE
    assert steps(events)[0]["risk"] == risk == runtime.store.list_tool_runs()[0]["risk"]
    assert any(e["type"] == "approval_required" for e in events) == (approval is not None)


def test_invalid_risk_fails_closed_and_baseline_cannot_be_lowered(settings):
    runtime, _ = scripted_runtime(settings, [call("write_test", mode="create")], [text("Failed.")])
    calls = []

    async def write(args, ctx):
        calls.append(args)
        return ToolResult(True, "Written")

    tool = make_dynamic_tool(write, lambda args, ctx: "unknown")
    runtime.registry.register(tool)
    _, events = run_turn(runtime, "Write")
    assert not calls and steps(events)[0]["status"] == "error"
    assert "invalid risk level" in steps(events)[0]["result"]
    tool.risk = RISK_SENSITIVE
    tool.risk_for = lambda args, ctx: RISK_READ
    assert tool.effective_risk({}, ToolContext("c", "r")) == RISK_SENSITIVE
    tool.risk_for = lambda args, ctx: None
    with pytest.raises(ToolError):
        tool.effective_risk({}, ToolContext("c", "r"))


def test_channel_reaches_prompt_and_tool_with_shared_memories(settings):
    runtime, provider = scripted_runtime(settings, [call("write_test", mode="create")], [text("Done.")])
    channels = []

    async def write(args, ctx):
        channels.append(ctx.channel)
        return ToolResult(True, "Written")

    runtime.registry.register(make_dynamic_tool(write, lambda args, ctx: RISK_ACT))
    runtime.memory.add("Prefers tea.", "preference")

    async def go():
        conversation = runtime.agent.start_turn(None, "Hello from my phone", channel="telegram")
        assert conversation["source"] == "telegram"
        return [event async for event in runtime.agent.run_turn(conversation, channel="telegram")]

    asyncio.run(go())
    prompt = provider.calls[0][0][0].content
    assert channels == ["telegram"] and "Prefers tea." in prompt and "butler-engineer" in prompt
    assert "phone chat" in prompt and "no tables or LaTeX" in prompt
    assert "Write maths in LaTeX" not in prompt


def test_missing_capabilities_follow_enabled_tools(runtime):
    names = ["remember", "open_app", "web_search", "read_page", "read_file", "write_file", "get_weather", "set_reminder"]
    prompt = build_system_prompt(runtime.prefs.all(), tool_names=names)
    missing = next(line for line in prompt.splitlines() if "You cannot yet:" in line)
    for ability in ("browse the web", "read files", "write files", "check live weather", "set reminders"):
        assert ability not in missing
    assert "hear or speak aloud" in missing
    disabled = build_system_prompt(runtime.prefs.all(), tool_names=["remember"])
    assert "browse the web" in disabled and "read files" in disabled and "set reminders" in disabled
    assert "Write maths in LaTeX" in disabled


def test_file_content_whitespace_is_preserved_without_model_schema_extension():
    schema = obj({"content": {"type": "string", "preserveWhitespace": True, "maxLength": 100}}, ["content"])
    for content in ("", " world", "\n    print('hello')\n"):
        assert validate_args(schema, {"content": content}) == ({"content": content}, None)
    assert validate_args(schema, {})[1] is not None
    tool = make_dynamic_tool(None, None)
    tool.parameters = schema
    assert "preserveWhitespace" not in tool.schema()["function"]["parameters"]["properties"]["content"]
    assert tool.parameters["properties"]["content"]["preserveWhitespace"]


def test_numeric_tool_arguments_reject_non_finite_and_invalid_values():
    schema = obj({"minutes": {"type": "number", "minimum": 0, "maximum": 100}})
    assert validate_args(schema, {"minutes": "2.5"}) == ({"minutes": 2.5}, None)
    for value in (True, float("nan"), float("inf"), "invalid", [], -1, 101, 10 ** 1000):
        assert validate_args(schema, {"minutes": value})[1] is not None
