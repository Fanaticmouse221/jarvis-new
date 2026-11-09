from datetime import datetime, timedelta, timezone

from jarvis.chat import ChatService, make_title
from jarvis.config import Settings
from jarvis.llm import ModelRouter
from jarvis.llm.fake import FakeProvider
from jarvis.persona import build_system_prompt, format_now, format_time_12h
from jarvis.storage import Store


def test_make_title():
    assert make_title("  Hello   there \nsecond line") == "Hello there"
    long = make_title("x" * 200)
    assert len(long) == 60 and long.endswith("…")


def test_context_respects_message_and_character_limits(tmp_path):
    settings = Settings(db_path=tmp_path / "t.db", max_history_messages=4, max_context_chars=50)
    store = Store(settings.db_path)
    service = ChatService(settings, store, ModelRouter([FakeProvider()]))
    conv = store.create_conversation()
    for i in range(6):
        store.add_message(conv["id"], "user", f"question {i}")
        store.add_message(conv["id"], "assistant", f"answer {i}")

    context = service.build_context(conv["id"])
    assert context[0].role == "system"
    history = context[1:]
    assert history[0].role == "user"  # never starts mid-exchange
    assert len(history) <= 4
    assert sum(len(m.content) for m in history) <= 50
    assert history[-1].content == "answer 5"


def test_twelve_hour_time_format():
    assert format_time_12h(datetime(2026, 11, 9, 18, 5)) == "6:05 PM"
    assert format_time_12h(datetime(2026, 11, 9, 0, 30)) == "12:30 AM"
    assert format_time_12h(datetime(2026, 11, 9, 12, 0)) == "12:00 PM"
    brisbane = timezone(timedelta(hours=10))
    assert format_now(datetime(2026, 11, 9, 18, 52, tzinfo=brisbane)) == "Monday 9 November 2026, 6:52 PM (UTC+10:00)"


def test_system_prompt_is_personalised_and_honest_about_capabilities():
    prompt = build_system_prompt(Settings(user_name="Jack", user_title="sir"))
    assert "JARVIS" in prompt
    assert "The user's name is Jack." in prompt
    assert '"sir"' in prompt
    assert "CANNOT yet" in prompt
    assert "12-hour" in prompt
