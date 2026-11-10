import sqlite3
from pathlib import Path

import pytest

from jarvis.config import Settings, parse_model_list, save_api_key
from jarvis.prefs import Prefs
from jarvis.storage import MIGRATIONS, Store, fts_query, keywords

from conftest import make_settings


# ----- configuration --------------------------------------------------------


def test_parse_model_list():
    specs = parse_model_list("groq:openai/gpt-oss-120b, openrouter:openai/gpt-oss-120b:free ,, ")
    assert [s.label for s in specs] == ["groq:openai/gpt-oss-120b", "openrouter:openai/gpt-oss-120b:free"]
    assert specs[1].model == "openai/gpt-oss-120b:free"  # only the first colon splits
    for bad in ("groq", "groq:", ":model"):
        with pytest.raises(ValueError):
            parse_model_list(bad)


def test_from_env_and_saving_a_key(tmp_path: Path, monkeypatch):
    for name in ("GROQ_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY", "JARVIS_MODELS", "JARVIS_PORT", "JARVIS_USER_TITLE"):
        monkeypatch.delenv(name, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("JARVIS_PORT=9001\nJARVIS_USER_TITLE=\n")
    settings = Settings.from_env(env_file)
    assert settings.port == 9001 and settings.host == "127.0.0.1" and settings.api_keys == {}
    assert settings.models[0].label == "groq:openai/gpt-oss-120b"

    updated = save_api_key(settings, "groq", "gsk_test_key_1234")
    assert updated.key_for("groq") == "gsk_test_key_1234"
    assert "GROQ_API_KEY=gsk_test_key_1234" in env_file.read_text()
    assert "JARVIS_PORT=9001" in env_file.read_text()  # other lines untouched

    removed = save_api_key(updated, "groq", None)
    assert removed.key_for("groq") == "" and "GROQ_API_KEY" not in env_file.read_text()
    with pytest.raises(ValueError):
        save_api_key(settings, "groq", "has a space")
    with pytest.raises(ValueError):
        save_api_key(settings, "nonsense", "x")


def test_prefs_validate_and_persist(tmp_path: Path):
    settings = make_settings(tmp_path)
    prefs = Prefs(Store(settings.db_path), settings)
    assert prefs.get("persona") == {"formality": "balanced", "wit": "subtle", "detail": "balanced"}

    prefs.update({"persona": {"wit": "playful"}, "user_name": " Jack ", "tool_policy": {"open_app": "ask"}})
    reopened = Prefs(Store(settings.db_path), settings)  # simulates a restart
    assert reopened.get("persona")["wit"] == "playful" and reopened.get("persona")["formality"] == "balanced"
    assert reopened.get("user_name") == "Jack"
    assert reopened.update({"tool_policy": {"open_app": None}})["tool_policy"] == {}

    for bad in (
        {"persona": {"wit": "hilarious"}},
        {"models": []},
        {"models": ["no-colon"]},
        {"max_steps": 99},
        {"memory_enabled": "yes"},
        {"tool_policy": {"open_app": "maybe"}},
        {"allowed_folders": [str(tmp_path / "missing")]},
        {"allowed_folders": [str(Path.home())]},
        {"unknown": 1},
    ):
        with pytest.raises(ValueError):
            prefs.update(bad)
    folder = tmp_path / "School"
    folder.mkdir()
    assert prefs.update({"allowed_folders": [str(folder)]})["allowed_folders"] == [str(folder.resolve())]


# ----- storage --------------------------------------------------------------


def test_upgrade_from_v1_database_keeps_conversations(tmp_path: Path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(MIGRATIONS[0])
    conn.execute("PRAGMA user_version = 1")
    conn.execute("INSERT INTO conversations VALUES ('c1', 'Old chat', '2026-11-09T08:00:00Z', '2026-11-09T08:00:00Z')")
    conn.execute(
        "INSERT INTO messages (conversation_id, role, content, model, created_at) "
        "VALUES ('c1', 'user', 'Explain the chain rule', NULL, '2026-11-09T08:00:00Z')"
    )
    conn.commit()
    conn.close()

    store = Store(path)
    assert store.get_conversation("c1")["title"] == "Old chat"
    assert store.get_messages("c1")[0]["parts"] is None
    assert store.search_messages("chain rule")[0]["conversation_id"] == "c1"  # old messages were indexed
    store.add_memory("Prefers 12-hour times.", "preference")  # new tables exist
    assert store.counts()["memories"] == 1


def test_conversations_messages_and_search(tmp_path: Path):
    store = Store(tmp_path / "t.db")
    a = store.create_conversation("Chemistry revision")
    b = store.create_conversation("Weekend plans")
    store.add_message(a["id"], "user", "Help me balance redox equations")
    reply = store.add_message(a["id"], "assistant", "Certainly.", "fake:x", [{"type": "text", "text": "Certainly."}])
    assert store.get_messages(a["id"])[1]["parts"] == [{"type": "text", "text": "Certainly."}]

    assert [c["title"] for c in store.list_conversations()] == ["Chemistry revision", "Weekend plans"]
    assert [c["id"] for c in store.list_conversations(query="redox")] == [a["id"]]
    assert [c["id"] for c in store.list_conversations(query="weekend")] == [b["id"]]
    assert store.search_messages("redox", exclude_conversation=a["id"]) == []

    assert store.delete_messages_from(a["id"], reply["id"]) == 1
    assert len(store.get_messages(a["id"])) == 1
    assert store.delete_conversation(a["id"])
    assert store.search_messages("redox") == []  # index cleaned up with the conversation
    assert Store(store.path).get_conversation(b["id"])["title"] == "Weekend plans"  # survives a restart


def test_memories_settings_usage_and_action_log(tmp_path: Path):
    store = Store(tmp_path / "t.db")
    assert store.fts
    one = store.add_memory("Prefers worked solutions shown step by step.", "preference")
    two = store.add_memory("Is studying for a chemistry exam.", "project", source="learned")
    assert [m["id"] for m in store.search_memories("chemistry exams")] == [two["id"]]  # stemming: exams ~ exam
    assert store.search_memories("quantum") == []
    store.update_memory(one["id"], content="Prefers brief answers.", pinned=True)
    assert store.search_memories("worked solutions") == [] and store.search_memories("brief")[0]["pinned"] is True
    assert store.list_memories()[0]["id"] == one["id"]  # pinned first
    store.touch_memories([two["id"]])
    assert store.get_memory(two["id"])["use_count"] == 1
    assert store.delete_memory(two["id"]) and store.search_memories("chemistry") == []

    store.set_setting("persona", {"wit": "off"})
    assert Store(store.path).get_setting("persona") == {"wit": "off"}

    store.record_usage("groq:m", prompt_tokens=100, completion_tokens=20)
    store.record_usage("groq:m", error=True, rate_limited=True)
    (row,) = store.usage_for_day()
    assert (row["requests"], row["prompt_tokens"], row["errors"], row["rate_limited"]) == (2, 100, 1, 1)
    assert store.requests_today() == 2

    store.add_tool_run(run_id="r", conversation_id=None, tool="open_app", title="Open Notepad", args={"name": "Notepad"},
                       risk="act", decision="auto", status="ok", summary="Opened Notepad", duration_ms=12)
    (run,) = store.list_tool_runs()
    assert run["args"] == {"name": "Notepad"} and run["status"] == "ok"


def test_search_helpers():
    assert keywords("What do you know about my chemistry exam?") == ["chemistry", "exam"]
    assert fts_query("the and of") is None
    assert fts_query("Chain-rule!") == '"chain"* OR "rule"*'
