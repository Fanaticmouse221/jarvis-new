from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from jarvis.telegram import TelegramError, TelegramService, markdown_to_html, split_message
from tests.conftest import call, scripted_runtime, text


TOKEN = "123456:telegram_test_token_1234567890"


class FakeTelegram:
    def __init__(self):
        self.requests = []
        self.updates = []
        self.reject_html = False
        self.poll_error = 0
        self.bot_id = 123456
        self.counter = 0

    async def __call__(self, request):
        method = request.url.path.rsplit("/", 1)[-1]
        data = json.loads(request.content)
        self.requests.append((method, data))
        if method == "getMe":
            result = {"id": self.bot_id, "is_bot": True, "username": "jarvis_test_bot"}
        elif method == "getUpdates":
            if self.poll_error:
                return httpx.Response(self.poll_error, json={"ok": False, "error_code": self.poll_error, "description": TOKEN})
            result, self.updates = self.updates, []
        elif method == "sendMessage":
            if self.reject_html and data.get("parse_mode"):
                return httpx.Response(400, json={"ok": False, "error_code": 400})
            self.counter += 1
            result = {"message_id": self.counter, "chat": {"id": data["chat_id"], "type": "private"}, "text": data["text"]}
        else:
            result = True
        return httpx.Response(200, json={"ok": True, "result": result})

    def messages(self):
        return [data for method, data in self.requests if method == "sendMessage"]


def message(content="Hello", owner=42, *, update_id=1, chat_type="private", **extra):
    return {"update_id": update_id, "message": {"chat": {"id": owner, "type": chat_type}, "from": {"id": owner, "is_bot": False}, "text": content, **extra}}


async def make_service(runtime):
    fake = FakeTelegram()
    service = TelegramService(runtime, api_base="https://telegram.invalid", transport=httpx.MockTransport(fake))
    await service.configure(TOKEN)
    return service, fake


async def until(predicate, timeout=3):
    async def wait():
        while not predicate():
            await asyncio.sleep(0.01)
    await asyncio.wait_for(wait(), timeout)


def test_private_pairing_strangers_and_hint(runtime):
    async def go():
        service, api = await make_service(runtime)
        code = service.status()["pairing_code"]
        assert len(code) == 6 and code.isdigit()
        assert TOKEN not in json.dumps(service.status())
        await service.handle_update(message(code, chat_type="group"))
        await service.handle_update(message("你好"))
        assert service.owner is None and api.messages() == []
        await service.handle_update(message(code))
        assert service.owner == 42 and service.status()["pairing_code"] is None
        count = len(api.messages())
        await service.handle_update(message("Open everything", owner=99))
        assert len(api.messages()) == count and service._queue.empty()
    asyncio.run(go())


def test_wrong_code_limits_and_rotation(runtime):
    async def go():
        service, api = await make_service(runtime)
        original = service.status()["pairing_code"]
        wrong = "999999" if original != "999999" else "000000"
        for _ in range(5):
            await service.handle_update(message(wrong))
        await service.handle_update(message(original))
        assert service.owner is None
        for _ in range(5):
            await service.handle_update(message(wrong, owner=99))
        assert service._wrong_total == 0
        assert service.status()["pairing_code"] != original
        assert api.messages() == []
    asyncio.run(go())


def test_message_runs_same_agent_memory_and_phone_context(settings):
    runtime, provider = scripted_runtime(settings, [text("Good evening, sir.")])
    runtime.memory.add("Jack likes cricket", kind="fact")
    async def go():
        service, api = await make_service(runtime)
        await service.handle_update(message(service.status()["pairing_code"]))
        await service.start()
        try:
            api.updates.append(message("Hello JARVIS", update_id=10))
            await until(lambda: any("Good evening" in m["text"] for m in api.messages()))
            conv = runtime.store.list_conversations()[0]
            assert conv["source"] == "telegram"
            assert [m["role"] for m in runtime.store.get_messages(conv["id"])] == ["user", "assistant"]
            prompt = provider.calls[0][0][0].content
            assert "Jack likes cricket" in prompt and "phone" in prompt.lower()
            polls = [data for name, data in api.requests if name == "getUpdates"]
            assert polls[0]["timeout"] == 25
            assert polls[0]["allowed_updates"] == ["message", "callback_query"]
            assert runtime.store.get_setting("telegram_offset") == 11
        finally:
            await service.stop()
        assert not runtime.active and service._client is None
    asyncio.run(go())


def callback(approval_id, message_id, owner=42, decision="y"):
    return {"callback_query": {"id": "callback-1", "from": {"id": owner}, "data": f"jarvis:{approval_id}:{decision}", "message": {"message_id": message_id, "chat": {"id": owner, "type": "private"}}}}


@pytest.mark.parametrize("approved", [True, False])
def test_approval_buttons_do_not_block_polling(settings, approved):
    runtime, _ = scripted_runtime(settings, [call("open_app", name="Notepad")], [text("Finished.")])
    runtime.update_prefs({"ask_every_action": True})
    async def go():
        service, api = await make_service(runtime)
        await service.handle_update(message(service.status()["pairing_code"]))
        await service.start()
        try:
            api.updates.append(message("Open Notepad", update_id=2))
            await until(lambda: bool(service._approvals))
            approval_id, (_, message_id) = next(iter(service._approvals.items()))
            assert runtime.launcher.launched == []
            await service.handle_update(callback(approval_id, message_id, owner=99))
            assert runtime.launcher.launched == [] and service._approvals
            # An owner cannot use a forged message id to approve another request.
            await service.handle_update(callback(approval_id, message_id + 10))
            assert service._approvals
            api.updates.append({"update_id": 3, **callback(approval_id, message_id, decision="y" if approved else "n")})
            await until(lambda: any("Finished." in m["text"] for m in api.messages()))
            assert runtime.launcher.launched == (["Notepad"] if approved else [])
            assert not runtime.approvals.pending()
            assert any(method == "editMessageText" for method, _ in api.requests)
        finally:
            await service.stop()
    asyncio.run(go())


def test_stop_cancels_approval_and_queue_then_accepts_new_message(settings):
    runtime, _ = scripted_runtime(settings, [call("open_app", name="Notepad")], [text("Still here.")])
    runtime.update_prefs({"ask_every_action": True})
    async def go():
        service, api = await make_service(runtime)
        await service.handle_update(message(service.status()["pairing_code"]))
        await service.start()
        try:
            await service.handle_update(message("Open Notepad"))
            await until(lambda: bool(service._approvals))
            await service.handle_update(message("Queued message"))
            await service.handle_update(message("/stop"))
            await until(lambda: not runtime.approvals.pending() and service._turn_task is None)
            assert service._queue.empty() and runtime.launcher.launched == [] and not runtime.active
            await service.handle_update(message("Hello again"))
            await until(lambda: any("Still here." in m["text"] for m in api.messages()))
        finally:
            await service.stop()
    asyncio.run(go())


def test_new_and_idle_conversations(runtime):
    async def go():
        service, api = await make_service(runtime)
        await service.handle_update(message(service.status()["pairing_code"]))
        first = service._conversation("First")
        assert service._conversation("same")["id"] == first["id"]
        await service._turn(message("/new")["message"])
        second = service._conversation("Second")
        assert first["id"] != second["id"]
        old = (datetime.now(timezone.utc) - timedelta(hours=9)).isoformat()
        with runtime.store._connect() as connection:
            connection.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (old, second["id"]))
        third = service._conversation("Third")
        assert third["id"] != second["id"] and third["source"] == "telegram"
    asyncio.run(go())


def test_unsupported_messages_commands_unlink_and_reminder(runtime):
    async def go():
        service, api = await make_service(runtime)
        await service.handle_update(message(service.status()["pairing_code"]))
        await service.handle_update(message("", voice={"file_id": "unused"}))
        assert "aren't supported" in api.messages()[-1]["text"]
        await service.handle_update(message("/help"))
        assert "/new" in api.messages()[-1]["text"]
        assert (await service.test_message())["ok"]
        assert await service.send_reminder("Reminder: revision")
        conv = runtime.store.get_setting("telegram_conversation")
        assert runtime.store.get_messages(conv)[-1]["content"] == "Reminder: revision"
        await service.unlink()
        assert service.owner is None and not await service.send_reminder("Should not send")
        with pytest.raises(ValueError, match="Link your phone"):
            await service.test_message()
        await service.remove()
        assert service.status()["state"] == "disabled" and not service.status()["token_hint"]
    asyncio.run(go())


def test_html_escaping_fallback_and_splitting(runtime):
    rendered = markdown_to_html('**Bold** *italic* `x < y`\n```py\na & b\n```\n[site](https://example.com/?x=1&y=2) <script>bad</script> [bad](javascript:alert)')
    assert "<b>Bold</b>" in rendered and "<i>italic</i>" in rendered
    assert "<code>x &lt; y</code>" in rendered and "<pre>a &amp; b\n</pre>" in rendered
    assert 'href="https://example.com/?x=1&amp;y=2"' in rendered
    assert "<script>" not in rendered and 'href="javascript' not in rendered
    original = "One paragraph.\n\n" + "😀<&" * 5000
    chunks = split_message(original)
    assert "".join(chunks) == original
    assert all(len(c.encode("utf-16-le")) // 2 <= 4096 and len(markdown_to_html(c)) <= 4096 for c in chunks)
    async def go():
        service, api = await make_service(runtime)
        api.reject_html = True
        await service.send_text(42, "**hello** <world>")
        sent = api.messages()
        assert sent[-2]["parse_mode"] == "HTML"
        assert "parse_mode" not in sent[-1] and sent[-1]["text"] == "**hello** <world>"
    asyncio.run(go())


@pytest.mark.parametrize("status,phrase", [(401, "token rejected"), (409, "Another program")])
def test_fatal_poll_error_is_safe_and_stops(runtime, status, phrase):
    async def go():
        service, api = await make_service(runtime)
        api.poll_error = status
        await service.start()
        try:
            await until(lambda: service.status()["state"] == "error")
            assert phrase in service.last_error and TOKEN not in service.last_error
            assert not service._running
        finally:
            await service.stop()
    asyncio.run(go())


def test_changed_bot_loses_owner_and_offset_and_secret_not_logged(runtime, caplog):
    caplog.set_level(logging.INFO, logger="httpx")
    async def go():
        service, api = await make_service(runtime)
        await service.handle_update(message(service.status()["pairing_code"]))
        runtime.store.set_setting("telegram_offset", 100)
        api.bot_id = 876543
        await service.configure(TOKEN)
        assert service.owner is None and runtime.store.get_setting("telegram_offset") == 0
        with pytest.raises(ValueError):
            await service.verify_token("invalid")
    asyncio.run(go())
    assert TOKEN not in caplog.text


def test_network_error_does_not_leak_url(runtime):
    async def fail(request):
        raise httpx.ConnectError(str(request.url), request=request)
    async def go():
        service = TelegramService(runtime, token=TOKEN, transport=httpx.MockTransport(fail))
        with pytest.raises(TelegramError) as caught:
            await service.verify_token(TOKEN)
        assert TOKEN not in str(caught.value)
    asyncio.run(go())


def test_disconnect_reconnect_during_lifespan_restarts_poller(runtime):
    async def go():
        service, api = await make_service(runtime)
        await service.start()
        await until(lambda: service.status()["state"] == "pairing")
        await service.remove()
        assert service._started and not service._running
        await service.configure(TOKEN)
        try:
            await until(lambda: service.status()["state"] == "pairing")
            assert service._running
            await service.handle_update(message(service.status()["pairing_code"]))
            assert service.owner == 42
        finally:
            await service.stop()
        assert not service._started
    asyncio.run(go())


def test_owner_persists_across_service_restart(runtime):
    async def go():
        service, api = await make_service(runtime)
        await service.handle_update(message(service.status()["pairing_code"]))
        await service.stop()
        restarted = TelegramService(runtime, token=TOKEN, transport=httpx.MockTransport(api))
        await restarted.start()
        try:
            await until(lambda: restarted.status()["state"] == "linked")
            assert restarted.owner == 42 and restarted.status()["pairing_code"] is None
            await restarted.handle_update(message("Wrong owner", owner=43))
            assert restarted._queue.empty()
        finally:
            await restarted.stop()
    asyncio.run(go())
