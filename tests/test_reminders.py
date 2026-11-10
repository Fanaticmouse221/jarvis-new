import asyncio
import base64
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from jarvis.reminders import ReminderService, as_utc, next_occurrence, windows_toast
from jarvis.storage import Store
from jarvis.tools import ToolContext, ToolError
from jarvis.tools.reminder_tools import cancel_reminder, list_reminders, set_reminder


NOW = datetime(2026, 11, 10, 8, 0, tzinfo=timezone.utc)


class FakeTelegram:
    def __init__(self, owner=123):
        self.owner = owner
        self.sent = []
        self.fail = False

    async def send_reminder(self, text, expected_owner=None):
        if expected_owner is not None and self.owner != expected_owner:
            return False
        if self.fail:
            raise RuntimeError("offline")
        self.sent.append(text)
        return bool(self.owner)


def service_at(tmp_path, telegram=None, toast=None):
    runtime = SimpleNamespace(store=Store(tmp_path / "reminders.db"), telegram=telegram or FakeTelegram())
    return ReminderService(runtime, toast=toast or (lambda text: True))


def test_reminders_persist_validate_and_cancel(tmp_path):
    service = service_at(tmp_path)
    created = service.create("Study chemistry", in_minutes=10, now=NOW)
    assert created["due_at"] == "2026-11-10T08:10:00.000Z" and created["status"] == "pending"
    assert "AM" in created["due_local"] or "PM" in created["due_local"]
    assert service_at(tmp_path).list()[0]["text"] == "Study chemistry"
    assert service.cancel(created["id"]) and not service.cancel(created["id"])
    assert service.list() == [] and service.list("all")[0]["status"] == "cancelled"
    for args in (
        {}, {"at": "2026-11-11"}, {"at": "nonsense"}, {"at": "2020-01-01T10:00"},
        {"in_minutes": 0}, {"in_minutes": -1}, {"in_minutes": True}, {"in_minutes": float("nan")},
        {"in_minutes": float("inf")}, {"in_minutes": 525601}, {"in_minutes": 10 ** 1000}, {"in_minutes": "ten"},
        {"at": "2026-11-11T18:30", "in_minutes": 5}, {"in_minutes": 5, "repeat": "monthly"},
    ):
        with pytest.raises(ValueError):
            service.create("Study", now=NOW, **args)
    with pytest.raises(ValueError):
        service.create(" ", in_minutes=5)
    with pytest.raises(ValueError):
        service.create("x" * 501, in_minutes=5)


def test_explicit_and_local_times_are_stored_in_utc(tmp_path):
    service = service_at(tmp_path)
    explicit = service.create("Study", at="2026-11-10T18:30:00+10:00", now=NOW)
    assert explicit["due_at"] == "2026-11-10T08:30:00.000Z"
    local = datetime.now().replace(second=0, microsecond=0) + timedelta(days=1)
    implicit = service.create("Study locally", at=local.isoformat())
    assert implicit["due_at"] == as_utc(local)


def test_due_notices_and_phone_delivery_survive_restart_without_duplicates(tmp_path):
    phone = FakeTelegram()
    toasts = []
    service = service_at(tmp_path, phone, lambda message: toasts.append(message) or True)
    reminder = service.create("Take a break", in_minutes=1, now=NOW)
    asyncio.run(service.tick(NOW + timedelta(minutes=3)))
    assert len(phone.sent) == len(toasts) == 1
    assert "(late)" in phone.sent[0]
    assert service.list() == [] and service.list("sent")[0]["id"] == reminder["id"]
    (notice,) = service.notices()
    assert notice["late"] and notice["reminder_id"] == reminder["id"]
    assert service.notices(after=notice["seq"]) == []
    restarted = service_at(tmp_path, phone, lambda message: toasts.append(message) or True)
    asyncio.run(restarted.tick(NOW + timedelta(minutes=4)))
    assert restarted.notices() == [notice] and len(phone.sent) == len(toasts) == 1


def test_phone_failure_retries_but_not_app_notice_or_toast(tmp_path):
    phone = FakeTelegram()
    phone.fail = True
    toasts = []
    service = service_at(tmp_path, phone, lambda message: toasts.append(message) or True)
    service.create("Revision", in_minutes=1, now=NOW)
    asyncio.run(service.tick(NOW + timedelta(minutes=1)))
    assert len(service.notices()) == len(toasts) == 1 and not phone.sent
    phone.fail = False
    restarted = service_at(tmp_path, phone, lambda message: toasts.append(message) or True)
    asyncio.run(restarted.tick(NOW + timedelta(minutes=2)))
    asyncio.run(restarted.tick(NOW + timedelta(minutes=3)))
    assert len(phone.sent) == len(toasts) == len(restarted.notices()) == 1


@pytest.mark.parametrize("previous_owner", [None, 123])
def test_unlinked_or_repaired_phone_does_not_receive_old_notices(tmp_path, previous_owner):
    phone = FakeTelegram(owner=previous_owner)
    phone.fail = bool(previous_owner)
    service = service_at(tmp_path, phone)
    service.create("Private reminder", in_minutes=1, now=NOW)
    asyncio.run(service.tick(NOW + timedelta(minutes=1)))
    phone.owner, phone.fail = 456, False
    asyncio.run(service.tick(NOW + timedelta(minutes=2)))
    assert not phone.sent and len(service.notices()) == 1


@pytest.mark.parametrize("repeat, days", [("daily", 1), ("weekly", 7)])
def test_recurrence_advances_atomically_and_skips_missed_occurrences(tmp_path, repeat, days):
    phone = FakeTelegram()
    service = service_at(tmp_path, phone)
    reminder = service.create("Study", in_minutes=1, repeat=repeat, now=NOW)
    asyncio.run(service.tick(NOW + timedelta(days=30, minutes=2)))
    recurring = service.list()[0]
    assert recurring["id"] == reminder["id"] and recurring["status"] == "pending"
    assert recurring["due_at"] > as_utc(NOW + timedelta(days=30, minutes=2))
    assert len(phone.sent) == 1 and len(service.notices()) == 1
    asyncio.run(service.tick(NOW + timedelta(days=30, minutes=3)))
    assert len(phone.sent) == 1


def test_weekday_recurrence_skips_weekend_in_local_time():
    friday = datetime(2026, 11, 13, 18, 30).astimezone()
    next_due = next_occurrence(friday, "weekdays", friday)
    assert next_due.astimezone().weekday() == 0
    assert next_due.astimezone().hour == 18 and next_due.astimezone().minute == 30


def test_two_ticks_cannot_claim_the_same_occurrence(tmp_path):
    phone = FakeTelegram()
    service = service_at(tmp_path, phone)
    service.create("Study", in_minutes=1, now=NOW)

    async def go():
        await asyncio.gather(service.tick(NOW + timedelta(minutes=1)), service.tick(NOW + timedelta(minutes=1)))

    asyncio.run(go())
    assert len(service.notices()) == len(phone.sent) == 1


def test_background_startup_delivers_overdue_and_stop_cancels(tmp_path):
    phone = FakeTelegram()
    service = service_at(tmp_path, phone)
    service.create("Overdue", in_minutes=1, now=datetime.now(timezone.utc) - timedelta(hours=1))

    async def go():
        await service.start()
        original = service._task
        await service.start()
        assert service._task is original
        for _ in range(100):
            if phone.sent:
                break
            await asyncio.sleep(0.005)
        await service.stop()
        assert service._task is None and original.done()

    asyncio.run(go())
    assert len(phone.sent) == 1 and "(late)" in phone.sent[0]


def test_reminder_tools_round_trip_and_errors(tmp_path):
    service = service_at(tmp_path)
    conversation = service.store.create_conversation()
    ctx = ToolContext(conversation["id"], "run", {"reminders": service})
    added = asyncio.run(set_reminder({"text": "Tea", "in_minutes": 10}, ctx))
    assert added.ok and "Tea" in added.text
    assert "Tea" in asyncio.run(list_reminders({}, ctx)).text
    assert asyncio.run(cancel_reminder({"id": added.data["reminder"]["id"]}, ctx)).ok
    assert "no pending reminders" in asyncio.run(list_reminders({}, ctx)).text
    with pytest.raises(ToolError):
        asyncio.run(set_reminder({"text": "Invalid"}, ctx))
    with pytest.raises(ToolError):
        asyncio.run(cancel_reminder({"id": 999}, ctx))


def test_windows_toast_encodes_content_as_data(monkeypatch):
    import jarvis.reminders as module

    monkeypatch.setattr(module.os, "name", "nt")
    invocations = []
    monkeypatch.setattr(module.subprocess, "run", lambda args, **kwargs: invocations.append((args, kwargs)) or SimpleNamespace(returncode=0))
    message = 'Remember <tea> & "milk"; $(Start-Process unsafe)'
    assert windows_toast(message)
    args, kwargs = invocations[0]
    script = base64.b64decode(args[-1]).decode("utf-16-le")
    assert message not in script and "Start-Process" not in script
    assert kwargs["timeout"] == 8 and "Hidden" in args
    payload = script.split("FromBase64String('")[1].split("')")[0]
    assert "&lt;tea&gt; &amp; &quot;milk&quot;" in base64.b64decode(payload).decode()
