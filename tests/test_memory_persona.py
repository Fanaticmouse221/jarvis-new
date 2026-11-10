import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from jarvis.llm import ModelRouter
from jarvis.llm.fake import FakeProvider
from jarvis.memory import CONTEXT_BUDGET, Learner, Memory, clean_content, looks_secret, parse_json_object
from jarvis.persona import build_system_prompt, format_now, format_time_12h, greeting
from jarvis.prefs import Prefs
from jarvis.runtime import Runtime
from jarvis.storage import Store

from conftest import FakeLauncher, make_settings, run_turn, scripted_runtime, text


def learner_with(store: Store, *replies: str) -> tuple[Learner, FakeProvider]:
    provider = FakeProvider("script", script=[[text(reply)] for reply in replies])
    router = ModelRouter([provider])
    return Learner(Memory(store), lambda: router), provider


# ----- memory rules -----------------------------------------------------------


def test_cleaning_and_secret_detection():
    assert clean_content("  Prefers   tea.\n") == "Prefers tea."
    for secret in ("My password is hunter2", "key gsk_abcdefghijklmnopqrstuv", "card 4111 1111 1111 1111", "api key: abc123"):
        assert looks_secret(secret)
        with pytest.raises(ValueError, match="password, key or card"):
            clean_content(secret)
    assert not looks_secret("Has an exam on 14 November 2026 in room 12")
    with pytest.raises(ValueError):
        clean_content("x" * 401)
    assert parse_json_object('Sure:\n```json\n{"add": []}\n```') == {"add": []}
    assert parse_json_object("no json here") == {}


def test_duplicates_are_refreshed_not_added(tmp_path):
    changes = []
    memory = Memory(Store(tmp_path / "t.db"), lambda action, m: changes.append(action))
    first, created = memory.add("Prefers worked solutions step by step.", "preference")
    again, created_again = memory.add("prefers worked solutions, step by step", "preference")
    assert created and not created_again and again["id"] == first["id"]
    assert len(memory.store.list_memories()) == 1

    memory.replace(first["id"], content="Prefers short answers.")
    memory.forget(first["id"])
    assert changes == ["saved", "updated", "forgotten"]
    assert memory.replace(999, content="Nothing here.") is None and memory.forget(999) is None


def test_context_includes_everything_while_it_fits(tmp_path):
    memory = Memory(Store(tmp_path / "t.db"))
    memory.add("Keep answers short.", "style")
    memory.add("Is building a personal assistant called JARVIS.", "project")
    memory.add("Prefers 12-hour times.", "preference")
    context = memory.context("what's the weather")  # nothing in the question matches, and it doesn't need to
    assert [m["content"] for m in context.style] == ["Keep answers short."]
    assert [m["kind"] for m in context.memories] == ["preference", "project"] and context.omitted == 0


def test_context_selects_by_relevance_once_memory_outgrows_the_budget(tmp_path):
    memory = Memory(Store(tmp_path / "t.db"))
    filler = [memory.add(f"Note {i}: " + f"detail{i} " * 30, "note")[0] for i in range(12)]
    target, _ = memory.add("The chemistry exam covers redox and equilibrium.", "note")
    pinned = memory.replace(filler[0]["id"], pinned=True)
    context = memory.context("help me revise for chemistry")
    ids = [m["id"] for m in context.memories]
    assert target["id"] in ids and pinned["id"] in ids
    assert context.omitted > 0 and sum(len(m["content"]) for m in context.memories) <= CONTEXT_BUDGET
    assert memory.store.get_memory(target["id"])["use_count"] == 1


# ----- learning ---------------------------------------------------------------


def test_reflection_adds_updates_and_logs(tmp_path):
    store = Store(tmp_path / "t.db")
    old = store.add_memory("Studies biology.", "personal")
    reply = json.dumps({"add": [{"kind": "project", "content": "Has a chemistry exam next week."}, {"kind": "note", "content": "password is hunter2"}],
                        "update": [{"id": old["id"], "content": "Studies biology and chemistry."}, {"id": 999, "content": "ghost"}]})
    learner, provider = learner_with(store, reply)
    conversation = store.create_conversation("Exam")

    changes = asyncio.run(learner.reflect(conversation["id"], "I've got a chemistry exam next week", "Then we'd best start."))
    assert [(c["action"], c["memory"]["content"]) for c in changes] == [
        ("updated", "Studies biology and chemistry."),
        ("learned", "Has a chemistry exam next week."),
    ]
    assert store.get_memory(changes[1]["memory"]["id"])["source"] == "learned"
    assert not any("hunter2" in m["content"] for m in store.list_memories())  # secrets are refused
    assert [run["tool"] for run in store.list_tool_runs()] == ["memory.learn", "memory.learn"]
    prompt = provider.calls[0][0][1].content
    assert f"#{old['id']} (personal) Studies biology." in prompt and "chemistry exam next week" in prompt


def test_reflection_is_skipped_when_there_is_nothing_personal(tmp_path):
    learner, provider = learner_with(Store(tmp_path / "t.db"), "{}")
    assert asyncio.run(learner.reflect("c", "Explain the chain rule", "...")) == []
    assert asyncio.run(learner.reflect("c", "thanks", "...")) == []
    assert asyncio.run(learner.reflect("c", "Tell me a fact about octopuses", "...")) == []
    assert asyncio.run(learner.reflect("c", "How do I integrate x squared?", "...")) == []
    assert provider.calls == []  # no model call was spent
    for personal in ("Actually, call me Jack from now on", "I've got a chemistry exam tomorrow", "Stop using bullet points", "My favourite band is Radiohead"):
        assert Learner.worth_reflecting(personal)


def test_reflection_survives_model_failure_and_nonsense(tmp_path):
    store = Store(tmp_path / "t.db")
    router = ModelRouter([FakeProvider("fail")])
    assert asyncio.run(Learner(Memory(store), lambda: router).reflect("c", "I prefer tea to coffee", "Noted.")) == []
    learner, _ = learner_with(store, "I couldn't find anything worth saving!")
    assert asyncio.run(learner.reflect("c", "I prefer tea to coffee", "Noted.")) == []


def test_learning_happens_automatically_after_a_turn_and_survives_restart(tmp_path):
    settings = make_settings(tmp_path)
    runtime = Runtime(settings, launcher=FakeLauncher())
    run_turn(runtime, "I'm studying chemistry for my exam next week")
    (memory,) = runtime.store.list_memories()
    assert memory["source"] == "learned" and "chemistry" in memory["content"]
    assert runtime.memory_changes()[0]["action"] == "learned"

    restarted = Runtime(settings, launcher=FakeLauncher())  # a new process reading the same database
    _, events = run_turn(restarted, "what do you know about me?")
    assert "chemistry" in events[-1]["message"]["content"]

    restarted.update_prefs({"auto_learn": False})
    run_turn(restarted, "I live in Brisbane")
    assert len(restarted.store.list_memories()) == 1


def test_long_conversations_get_a_rolling_summary(tmp_path):
    settings = make_settings(tmp_path, max_context_chars=300)
    runtime, provider = scripted_runtime(settings, *[[text(f"Reply {i} " + "x" * 80)] for i in range(5)], [text("They discussed revision topics one to four.")], [text("Final reply.")])
    conversation_id = None
    for i in range(5):
        conversation_id, _ = run_turn(runtime, f"Question {i} " + "y" * 80, conversation_id)
    conversation = runtime.store.get_conversation(conversation_id)
    assert conversation["summary"] == "They discussed revision topics one to four." and conversation["summary_upto"] > 0

    run_turn(runtime, "And one more", conversation_id)
    system_prompt = provider.calls[-1][0][0].content
    assert "Earlier in this conversation" in system_prompt and "revision topics one to four" in system_prompt


# ----- personality --------------------------------------------------------------


def prefs_for(tmp_path, **patch):
    settings = make_settings(tmp_path)
    prefs = Prefs(Store(settings.db_path), settings)
    return prefs.update(patch) if patch else prefs.all()


def test_prompt_reflects_personality_dials(tmp_path):
    default = build_system_prompt(prefs_for(tmp_path), tool_names=["remember"])
    assert "butler-engineer" in default and "Dry, understated wit" in default and 'Address the user as "sir"' in default
    assert "Spotify is open, sir." in default

    changed = build_system_prompt(
        prefs_for(tmp_path, persona={"wit": "off", "formality": "casual", "detail": "brief"}, user_title="", user_name="Jack"),
        tool_names=["remember"],
    )
    assert "No humour" in changed and "Relaxed and friendly" in changed and "as short as accuracy allows" in changed
    assert "Don't use a title" in changed and "Spotify is open." in changed and "Address the user as" not in changed
    assert "Jack's personal AI assistant" in changed and "The user's name is Jack." in changed


def test_prompt_carries_standing_instructions_memories_and_continuity(tmp_path):
    prompt = build_system_prompt(
        prefs_for(tmp_path, custom_instructions="Never use bullet points."),
        tool_names=["remember", "open_app"],
        style_rules=[{"id": 4, "content": "Wants shorter answers."}],
        memories=[{"id": 7, "kind": "preference", "content": "Prefers 12-hour times."}, {"id": 9, "kind": "project", "content": "Is building JARVIS."}],
        omitted_memories=3,
        summary="They planned a chemistry revision timetable.",
        recent_titles=['"Chain rule practice" (2026-11-09)'],
    )
    rules = prompt.index("Standing instructions from the user")
    assert rules < prompt.index("## Honesty") and "- Wants shorter answers." in prompt and "Never use bullet points." in prompt
    assert "Preferences:\n- [#7] Prefers 12-hour times." in prompt and "- [#9] Is building JARVIS." in prompt
    assert "3 more memories are stored" in prompt
    assert "chemistry revision timetable" in prompt and "Chain rule practice" in prompt


def test_prompt_is_honest_about_capabilities(tmp_path):
    with_tools = build_system_prompt(prefs_for(tmp_path), tool_names=["remember", "open_app"])
    assert "You have real tools" in with_tools and "You cannot yet: browse the web" in with_tools
    without = build_system_prompt(prefs_for(tmp_path), tool_names=[])
    assert "You have no tools" in without and "## Memory" not in without
    memory_off = build_system_prompt(prefs_for(tmp_path, memory_enabled=False), tool_names=["open_app"])
    assert "## Memory" not in memory_off and "What you know about the user" not in memory_off


def test_time_formatting_and_greeting():
    assert format_time_12h(datetime(2026, 11, 9, 18, 5)) == "6:05 PM"
    assert format_time_12h(datetime(2026, 11, 9, 0, 30)) == "12:30 AM"
    brisbane = timezone(timedelta(hours=10))
    assert format_now(datetime(2026, 11, 9, 18, 52, tzinfo=brisbane)) == "Monday 9 November 2026, 6:52 PM (UTC+10:00)"
    assert greeting(datetime(2026, 11, 9, 9, 0), "sir") == "Good morning, sir."
    assert greeting(datetime(2026, 11, 9, 14, 0), "") == "Good afternoon."
    assert greeting(datetime(2026, 11, 9, 23, 0), "Jack") == "Good evening, Jack."
