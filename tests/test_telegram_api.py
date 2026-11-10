import httpx

from conftest import Client
from tests.test_telegram import FakeTelegram, TOKEN


def test_token_is_verified_persisted_masked_and_removed(runtime, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    runtime.telegram.transport = httpx.MockTransport(FakeTelegram())
    client = Client(runtime)
    response = client.post("/api/telegram/token", json={"token": TOKEN})
    assert response.status_code == 200
    assert TOKEN not in response.text
    assert response.json()["token_hint"].endswith(TOKEN[-4:])
    assert TOKEN in runtime.settings.env_path.read_text()
    assert TOKEN not in client.get("/api/settings").text
    assert len(client.get("/api/telegram").json()["pairing_code"]) == 6
    assert client.post("/api/telegram/test").status_code == 422
    assert client.delete("/api/telegram").status_code == 200
    assert TOKEN not in runtime.settings.env_path.read_text()
    assert not client.get("/api/telegram").json()["enabled"]


def test_rejected_token_is_not_saved_and_error_is_safe(runtime):
    runtime.telegram.transport = httpx.MockTransport(lambda request: httpx.Response(
        401, json={"ok": False, "error_code": 401, "description": TOKEN}))
    client = Client(runtime)
    response = client.post("/api/telegram/token", json={"token": TOKEN})
    assert response.status_code == 502
    assert "rejected" in response.text and TOKEN not in response.text
    assert not runtime.settings.env_path.exists()
    assert not runtime.telegram.token
    assert client.get("/api/telegram", headers={"X-Jarvis-Token": "wrong"}).status_code == 401
