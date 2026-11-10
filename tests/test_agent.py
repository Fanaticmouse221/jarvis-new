import asyncio

import pytest

from jarvis.llm import LLMError
from jarvis.tools import RISK_SENSITIVE, Tool, ToolResult, validate_args
from jarvis.tools.base import obj

from conftest import call, run_turn, scripted_runtime, steps, text


def types(events):
    return [event["type"] for event in events if event["type"] != "token"]


# ----- the loop -----------------------------------------------------------------


def test_tool_call_runs_for_real_and_is_recorded(settings):
    runtime, provider = scripted_runtime(
        settings,
        [text("One moment."), call("remember", content="Prefers tea to coffee.", kind="preference")],
        [text("Noted, sir.")],
        learn=True,
    )
    conversation_id, events = run_turn(runtime, "By the way, I prefer tea to coffee")
    assert types(events) == ["conversation", "model", "tool_start", "tool_end", "done"]

    (memory,) = runtime.store.list_memories()  # the independent check: it is really in the database
    assert memory["content"] == "Prefers tea to coffee." and memory["source"] == "told"

    message = events[-1]["message"]
    assert [part["type"] for part in message["parts"]] == ["text", "tool", "text"]
    assert message["content"] == "One moment.\n\nNoted, sir."
    step = message["parts"][1]
    assert step["status"] == "ok" and step["title"] == "Remember: Prefers tea to coffee." and step["decision"] == "auto"

    (run,) = runtime.store.list_tool_runs()
    assert (run["tool"], run["status"], run["decision"], run["conversation_id"]) == ("remember", "ok", "auto", conversation_id)
    # The second model call saw the tool result, so its confirmation was grounded in it.
    second_call = provider.calls[1][0]
    assert second_call[-1].role == "tool" and second_call[-1].content.startswith("Saved to memory")
    assert len(provider.calls) == 2  # the model used `remember` itself, so no extra learning call was spent


def test_tool_failures_are_reported_to_the_model_not_hidden(settings):
    runtime, provider = scripted_runtime(
        settings,
        [call("open_app", name="Photoshop")],
        [call("launch_rocket", target="moon")],
        [call("forget", id="not-a-number")],
        [call("forget")],
        [text("I couldn't do that.")],
    )
    _, events = run_turn(runtime, "open photoshop")
    statuses = [(s["tool"], s["status"]) for s in steps(events)]
    assert statuses == [("open_app", "error"), ("launch_rocket", "error"), ("forget", "error"), ("forget", "error")]
    results = [m.content for m in provider.calls[-1][0] if m.role == "tool"]
    assert results[0].startswith("ERROR: No installed app matches 'Photoshop'")
    assert "no tool called 'launch_rocket'" in results[1]
    assert "must be a whole number" in results[2] and "missing required argument 'id'" in results[3]
    assert runtime.launcher.launched == []


def test_crashing_or_slow_tool_does_not_break_the_turn(settings):
    runtime, _ = scripted_runtime(settings, [call("boom")], [call("slow")], [text("Both failed.")])

    async def boom(args, ctx):
        raise RuntimeError("kaboom")

    async def slow(args, ctx):
        await asyncio.sleep(5)

    make = lambda name, handler, timeout: Tool(name, "computer", name, "", obj({}), "read", handler, lambda a: name, timeout)
    runtime.registry.register(make("boom", boom, 5), make("slow", slow, 0.05))
    _, events = run_turn(runtime, "go")
    summaries = [s["summary"] for s in steps(events)]
    assert "failed unexpectedly (RuntimeError)" in summaries[0] and "Timed out" in summaries[1]
    assert events[-1]["type"] == "done"


def test_step_limit_forces_a_final_answer(settings):
    runtime, provider = scripted_runtime(settings, *[[call("get_system_info")] for _ in range(2)], [text("I ran out of steps.")])
    runtime.update_prefs({"max_steps": 2})
    _, events = run_turn(runtime, "loop forever")
    assert len(steps(events)) == 2 and events[-1]["message"]["content"] == "I ran out of steps."
    final_messages, final_tools = provider.calls[2]
    assert final_tools is None and "step limit" in final_messages[-1].content


def test_model_error_mid_task_keeps_what_was_done(settings):
    runtime, _ = scripted_runtime(settings, [call("remember", content="Likes jazz.", kind="preference")])
    runtime.router.providers[0].script.append([])  # second model call returns nothing -> failure
    conversation_id, events = run_turn(runtime, "I like jazz")
    assert events[-1]["type"] == "error"
    saved = runtime.store.get_messages(conversation_id)[-1]
    assert saved["role"] == "assistant" and "[Response interrupted]" in saved["content"]
    assert saved["parts"][0]["status"] == "ok"


def test_oversized_request_is_retried_with_less_history(settings):
    runtime, provider = scripted_runtime(settings, [text("First.")], [text("Shorter now.")])
    conversation_id, _ = run_turn(runtime, "Hello")
    original = provider.stream_chat
    sizes = []

    async def too_large_once(messages, tools=None):
        sizes.append(len(messages))
        if len(sizes) == 1:
            raise LLMError("too large", status=413)
        async for event in original(messages, tools):
            yield event

    provider.stream_chat = too_large_once
    _, events = run_turn(runtime, "Second question", conversation_id)
    assert sizes == [4, 2]  # system + history + question, then system + question only
    assert [e["text"] for e in events if e["type"] == "status"] == ["That was too large for the model's limit. Retrying with less history."]
    assert events[-1]["message"]["content"] == "Shorter now."


# ----- context ------------------------------------------------------------------


def test_earlier_tool_use_is_replayed_so_actions_stay_grounded(settings):
    runtime, provider = scripted_runtime(
        settings, [call("open_app", name="notepad")], [text("Notepad is open, sir.")], [text("Certainly.")]
    )
    conversation_id, _ = run_turn(runtime, "open notepad")
    assert runtime.launcher.launched == ["Notepad"]
    run_turn(runtime, "thanks", conversation_id)
    history = provider.calls[-1][0]
    assert [(m.role, bool(m.tool_calls)) for m in history[1:]] == [
        ("user", False), ("assistant", True), ("tool", False), ("assistant", False), ("user", False),
    ]
    assert history[2].tool_calls[0].name == "open_app" and history[3].tool_call_id == history[2].tool_calls[0].id


def test_context_respects_limits_and_starts_with_the_user(settings):
    runtime, provider = scripted_runtime(settings, *[[text(f"answer {i}")] for i in range(6)])
    runtime.agent.settings = settings.__class__(**{**settings.__dict__, "max_history_messages": 4, "max_context_chars": 60})
    conversation_id = None
    for i in range(6):
        conversation_id, _ = run_turn(runtime, f"question {i}", conversation_id)
    history = provider.calls[-1][0][1:]
    assert history[0].role == "user" and history[-1].content == "question 5" and len(history) <= 4


def test_memory_and_recent_conversations_reach_the_model(settings):
    runtime, provider = scripted_runtime(settings, [text("Morning.")], [text("Of course.")])
    runtime.memory.add("Prefers 12-hour times.", "preference")
    runtime.memory.add("Wants shorter answers.", "style")
    run_turn(runtime, "Plan my chemistry revision")
    run_turn(runtime, "Something new")
    system = provider.calls[-1][0][0].content
    assert "[#1] Prefers 12-hour times." in system and "- Wants shorter answers." in system
    assert 'Recent conversations (newest first): "Plan my chemistry revision"' in system

    runtime.update_prefs({"memory_enabled": False})
    runtime.router.providers[0].script.append([text("Fine.")])
    run_turn(runtime, "Again")
    system, tools = provider.calls[-1][0][0].content, provider.calls[-1][1]
    assert "Prefers 12-hour times" not in system and "remember" not in [t["function"]["name"] for t in tools]


# ----- approvals ----------------------------------------------------------------


def approve_when_asked(runtime, approve=True, always=False):
    async def watcher():
        while not runtime.approvals.pending():
            await asyncio.sleep(0.005)
        runtime.approvals.resolve(runtime.approvals.pending()[0]["id"], approve, always)

    return watcher


def run_with_approval(runtime, message, **decision):
    async def go():
        conversation = runtime.agent.start_turn(None, message)
        watcher = asyncio.create_task(approve_when_asked(runtime, **decision)())
        events = [event async for event in runtime.agent.run_turn(conversation)]
        await watcher
        return events

    return asyncio.run(go())


def test_ask_first_action_waits_for_approval(settings):
    runtime, _ = scripted_runtime(settings, [call("open_app", name="spotify")], [text("Spotify is open.")])
    runtime.update_prefs({"tool_policy": {"open_app": "ask"}})
    events = run_with_approval(runtime, "open spotify", approve=True)
    assert types(events) == ["conversation", "model", "tool_start", "approval_required", "approval_resolved", "tool_end", "done"]
    request = next(e for e in events if e["type"] == "approval_required")
    assert request["title"] == "Open spotify" and request["reason"] == "You've set this action to ask first." and request["can_always"]
    assert runtime.launcher.launched == ["Spotify"] and steps(events)[0]["decision"] == "approved"


def test_declined_action_never_runs_and_the_model_is_told(settings):
    runtime, provider = scripted_runtime(settings, [call("open_app", name="spotify")], [text("Very well, I've left it closed.")])
    runtime.update_prefs({"ask_every_action": True})
    events = run_with_approval(runtime, "open spotify", approve=False)
    assert runtime.launcher.launched == []
    assert steps(events)[0]["status"] == "denied" and not next(e for e in events if e["type"] == "approval_required")["can_always"]
    assert provider.calls[1][0][-1].content == "ERROR: The user declined this action."
    assert runtime.store.list_tool_runs()[0]["decision"] == "denied"


def test_always_allow_changes_the_permission(settings):
    runtime, _ = scripted_runtime(
        settings, [call("open_app", name="notepad")], [text("Done.")], [call("open_app", name="calculator")], [text("Done.")]
    )
    runtime.update_prefs({"tool_policy": {"open_app": "ask"}})
    run_with_approval(runtime, "open notepad", approve=True, always=True)
    assert runtime.prefs.get("tool_policy")["open_app"] == "allow"
    _, events = run_turn(runtime, "open calculator")  # no approval needed any more
    assert "approval_required" not in types(events) and runtime.launcher.launched == ["Notepad", "Calculator"]


def test_sensitive_and_tainted_actions_always_ask(settings):
    runtime, _ = scripted_runtime(settings)

    async def nothing(args, ctx):
        return ToolResult(True, "ok")

    wipe = Tool("wipe", "computer", "Wipe", "", obj({}), RISK_SENSITIVE, nothing, lambda a: "Wipe everything")
    runtime.registry.register(wipe)
    prefs = runtime.update_prefs({"tool_policy": {"wipe": "allow"}})
    assert runtime.registry.policy(wipe, prefs) == "ask"  # "allow" is not honoured for sensitive tools

    from jarvis.tools import ToolContext

    open_app = runtime.registry.get("open_app")
    recall = runtime.registry.get("recall")
    clean, tainted = ToolContext("c", "r"), ToolContext("c", "r", tainted=True)
    assert runtime.agent._approval_reason(wipe, prefs, clean) == "This can't easily be undone."
    assert runtime.agent._approval_reason(open_app, prefs, clean) is None
    assert "outside content" in runtime.agent._approval_reason(open_app, prefs, tainted)
    assert runtime.agent._approval_reason(recall, prefs, tainted) is None  # reading is always fine


def test_switched_off_tool_is_not_offered(settings):
    runtime, provider = scripted_runtime(settings, [text("I can't open apps at the moment.")])
    runtime.update_prefs({"tool_policy": {"open_app": "off"}})
    run_turn(runtime, "open notepad")
    assert "open_app" not in [t["function"]["name"] for t in provider.calls[0][1]]


# ----- stop, regenerate, edit -----------------------------------------------------


def test_stopping_mid_task_saves_progress_and_cancels_the_wait(settings):
    runtime, _ = scripted_runtime(settings, [text("Opening it now."), call("open_app", name="spotify")])
    runtime.update_prefs({"tool_policy": {"open_app": "ask"}})

    async def go():
        conversation = runtime.agent.start_turn(None, "open spotify")
        stream = runtime.agent.run_turn(conversation)
        async for event in stream:
            if event["type"] == "approval_required":
                break
        await stream.aclose()  # what happens when the user presses Stop
        return conversation["id"]

    conversation_id = asyncio.run(go())
    saved = runtime.store.get_messages(conversation_id)[-1]
    assert "[Stopped]" in saved["content"] and saved["parts"][1]["status"] == "cancelled"
    assert runtime.approvals.pending() == [] and runtime.launcher.launched == []


def test_regenerate_and_edit(settings):
    runtime, provider = scripted_runtime(settings, [text("First.")], [text("Second.")], [text("Third.")])
    conversation_id, _ = run_turn(runtime, "Tell me a fact")
    run_turn(runtime, conversation_id=conversation_id, regenerate=True)
    messages = runtime.store.get_messages(conversation_id)
    assert [(m["role"], m["content"]) for m in messages] == [("user", "Tell me a fact"), ("assistant", "Second.")]

    run_turn(runtime, "Tell me a different fact", conversation_id, edit_message_id=messages[0]["id"])
    assert [m["content"] for m in runtime.store.get_messages(conversation_id)] == ["Tell me a different fact", "Third."]
    for bad in ({"message": ""}, {"message": "x", "edit_message_id": 999}, {"regenerate": True, "conversation_id": None}):
        with pytest.raises(ValueError):
            runtime.agent.start_turn(bad.pop("conversation_id", conversation_id), bad.pop("message", ""), **bad)


# ----- tools --------------------------------------------------------------------


def test_argument_validation():
    schema = obj({"name": {"type": "string", "maxLength": 5}, "id": {"type": "integer", "minimum": 1}, "kind": {"type": "string", "enum": ["a", "b"]}, "flag": {"type": "boolean"}}, ["name"])
    assert validate_args(schema, {"name": " ab ", "id": "#12", "flag": "true", "extra": 1}) == ({"name": "ab", "id": 12, "flag": True}, None)
    assert validate_args(schema, {"name": 7, "id": 3.0}) == ({"name": "7", "id": 3}, None)
    for bad, message in (
        ({}, "missing required argument 'name'"),
        ({"name": "toolong"}, "too long"),
        ({"name": "ab", "id": 0}, "at least 1"),
        ({"name": "ab", "kind": "c"}, "must be one of"),
        ({"name": "ab", "flag": "maybe"}, "true or false"),
        ("nope", "JSON object"),
    ):
        assert message in validate_args(schema, bad)[1]


def test_app_matching_urls_and_system_info(settings):
    runtime, _ = scripted_runtime(
        settings,
        [call("open_app", name="vs code")], [call("open_app", name="calc")], [call("open_url", url="example.com/page")],
        [call("open_url", url="file:///etc/passwd")], [call("get_system_info")], [text("Done.")],
    )
    opened = []
    runtime.services["open_url"] = lambda url: opened.append(url) or True
    _, events = run_turn(runtime, "do several things")
    results = steps(events)
    assert results[0]["status"] == "error" and "Visual Studio Code" in results[0]["result"]  # suggests the near miss
    assert results[1]["status"] == "ok" and runtime.launcher.launched == ["Calculator"]
    assert results[2]["status"] == "ok" and opened == ["https://example.com/page"]
    assert results[3]["status"] == "error" and "Only http and https" in results[3]["result"]
    assert results[4]["status"] == "ok" and "Memory:" in results[4]["result"] and "CPU:" in results[4]["result"]


def test_memory_tools_round_trip(settings):
    runtime, provider = scripted_runtime(
        settings,
        [text("Titration it is.")],
        [call("remember", content="Favourite subject is chemistry.", kind="personal")],
        [call("remember", content="Favourite subject is maths.", kind="personal", replaces_id=1)],
        [call("recall", query="favourite subject")],
        [call("remember", content="My password is hunter2", kind="note")],
        [call("forget", id=1)],
        [call("recall", query="favourite subject")],
        [text("All done.")],
    )
    first, _ = run_turn(runtime, "Talk about redox titration methods")
    _, events = run_turn(runtime, "run the memory script")
    results = steps(events)
    assert [r["status"] for r in results] == ["ok", "ok", "ok", "error", "ok", "ok"]
    assert results[1]["data"]["action"] == "updated" and "#1 (personal) Favourite subject is maths." in results[2]["result"]
    assert "doesn't store those" in results[3]["result"] and results[5]["result"] == "Nothing in memory matches that."
    assert runtime.store.list_memories() == []

    runtime.router.providers[0].script += [[call("search_conversations", query="titration")], [text("Found it.")]]
    _, events = run_turn(runtime, "what did we say about titration?")
    assert "Talk about redox titration methods" in steps(events)[0]["result"]
