import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from jarvis.llm import LLMError
from jarvis.runtime import Runtime
from jarvis.server import create_app

from conftest import Client, FakeLauncher, make_settings, parse_sse


def chat(client, message, conversation_id=None, **extra):
    response = client.post("/api/chat", json={"message": message, "conversation_id": conversation_id, **extra})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    return parse_sse(response.text)


# ----- security -------------------------------------------------------------------


def test_api_refuses_callers_other_than_its_own_interface(runtime):
    app = create_app(runtime=runtime)
    anonymous = TestClient(app)
    assert anonymous.get("/api/bootstrap").status_code == 401  # no token
    assert anonymous.post("/api/chat", json={"message": "open notepad"}).status_code == 401
    assert runtime.launcher.launched == []

    token = {"X-Jarvis-Token": runtime.token}
    assert anonymous.get("/api/bootstrap", headers=token).status_code == 200
    assert anonymous.get("/api/bootstrap", headers={**token, "Origin": "https://evil.example"}).status_code == 403
    assert anonymous.get("/api/bootstrap", headers={**token, "Host": "evil.example"}).status_code == 403  # DNS rebinding
    assert anonymous.get("/api/bootstrap", headers={**token, "Origin": "http://testserver"}).status_code == 200


def test_page_carries_the_token_and_static_files_are_served(client):
    page = client.get("/")
    assert page.status_code == 200 and client.runtime.token in page.text and "{{JARVIS_TOKEN}}" not in page.text
    assert page.headers["cache-control"] == "no-store"
    assert client.get("/static/js/main.js").status_code == 200
    assert Runtime(client.runtime.settings).token == client.runtime.token  # stable across restarts


# ----- chat -----------------------------------------------------------------------


def test_chat_streams_tool_steps_and_persists_them(client):
    events = chat(client, "Remember that I prefer short answers")
    types = [e["type"] for e in events if e["type"] != "token"]
    assert types == ["conversation", "model", "tool_start", "tool_end", "done"]
    conversation_id = events[0]["conversation"]["id"]
    assert events[0]["conversation"]["title"] == "Remember that I prefer short answers"

    data = client.get(f"/api/conversations/{conversation_id}").json()
    assert [m["role"] for m in data["messages"]] == ["user", "assistant"]
    assert data["messages"][1]["parts"][0]["tool"] == "remember" and data["messages"][1]["model"] == "fake:agent"
    assert client.get("/api/memories").json()["memories"][0]["kind"] == "style"

    chat(client, "open notepad", conversation_id)
    assert client.runtime.launcher.launched == ["Notepad"]
    runs = client.get("/api/activity").json()["runs"]
    assert [run["tool"] for run in runs] == ["open_app", "remember"] and runs[0]["conversation_title"]


def test_chat_validation_regenerate_and_edit(client):
    assert client.post("/api/chat", json={"message": "hi", "conversation_id": "missing"}).status_code == 404
    assert client.post("/api/chat", json={"message": "   "}).status_code == 422
    assert client.post("/api/chat", json={"regenerate": True}).status_code == 422

    conversation_id = chat(client, "open notepad")[0]["conversation"]["id"]
    chat(client, "", conversation_id, regenerate=True)
    messages = client.get(f"/api/conversations/{conversation_id}").json()["messages"]
    assert len(messages) == 2 and client.runtime.launcher.launched == ["Notepad", "Notepad"]
    chat(client, "open calculator", conversation_id, edit_message_id=messages[0]["id"])
    assert [m["content"] for m in client.get(f"/api/conversations/{conversation_id}").json()["messages"]][0] == "open calculator"


def test_approval_round_trip_over_http(tmp_path):
    runtime = Runtime(make_settings(tmp_path), launcher=FakeLauncher())
    runtime.update_prefs({"tool_policy": {"open_app": "ask"}})
    app = create_app(runtime=runtime)

    async def go():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver", headers={"X-Jarvis-Token": runtime.token}) as http:
            pending_chat = asyncio.create_task(http.post("/api/chat", json={"message": "open spotify"}))
            while not runtime.approvals.pending():
                await asyncio.sleep(0.01)
            waiting = (await http.get("/api/activity")).json()["pending"]
            assert waiting[0]["title"] == "Open spotify" and runtime.launcher.launched == []
            approval_id = waiting[0]["id"]
            assert (await http.post(f"/api/approvals/{approval_id}", json={"approve": True})).status_code == 200
            response = await pending_chat
            assert (await http.post(f"/api/approvals/{approval_id}", json={"approve": True})).status_code == 404
            return parse_sse(response.text)

    events = asyncio.run(go())
    assert [e["decision"] for e in events if e["type"] == "approval_resolved"] == ["approved"]
    assert runtime.launcher.launched == ["Spotify"]


def test_errors_reach_the_interface_without_inventing_a_reply(tmp_path):
    runtime = Runtime(make_settings(tmp_path, "groq:openai/gpt-oss-120b"), launcher=FakeLauncher())
    client = Client(runtime)
    assert client.get("/api/bootstrap").json()["models"]["ready"] == []
    events = chat(client, "Hello?")
    assert events[-1]["type"] == "error" and "API key" in events[-1]["message"]
    messages = client.get(f"/api/conversations/{events[0]['conversation']['id']}").json()["messages"]
    assert [m["role"] for m in messages] == ["user"]


# ----- conversations ----------------------------------------------------------------


def test_conversation_management(client):
    first = chat(client, "Help me plan chemistry revision")[0]["conversation"]["id"]
    second = chat(client, "open notepad")[0]["conversation"]["id"]
    assert [c["id"] for c in client.get("/api/conversations").json()] == [second, first]
    assert [c["id"] for c in client.get("/api/conversations", params={"q": "chemistry"}).json()] == [first]

    renamed = client.patch(f"/api/conversations/{first}", json={"title": "  Chem   plan "})
    assert renamed.json()["title"] == "Chem plan"
    export = client.get(f"/api/conversations/{first}/export")
    assert export.text.startswith("# Chem plan") and "**You**" in export.text and "**JARVIS**" in export.text

    assert client.delete(f"/api/conversations/{first}").status_code == 204
    assert client.get(f"/api/conversations/{first}").status_code == 404
    assert client.delete("/api/conversations").json() == {"deleted": 1}
    assert client.get("/api/conversations").json() == []


# ----- memory -----------------------------------------------------------------------


def test_memory_management_endpoints(client):
    created = client.post("/api/memories", json={"content": "Is left-handed.", "kind": "personal"}).json()
    assert created["created"] and created["memory"]["source"] == "user"
    memory_id = created["memory"]["id"]
    assert not client.post("/api/memories", json={"content": "is left handed", "kind": "personal"}).json()["created"]
    assert client.post("/api/memories", json={"content": "My password is hunter2"}).status_code == 422

    updated = client.patch(f"/api/memories/{memory_id}", json={"content": "Is left-handed and plays chess.", "pinned": True}).json()
    assert updated["pinned"] is True and "chess" in updated["content"]
    assert client.patch(f"/api/memories/{memory_id}", json={"kind": "nonsense"}).status_code == 422
    assert client.patch("/api/memories/999", json={"pinned": True}).status_code == 404

    listing = client.get("/api/memories", params={"q": "chess"}).json()
    assert [m["id"] for m in listing["memories"]] == [memory_id] and listing["total"] == 1
    assert client.get("/api/memories", params={"kind": "project"}).json()["memories"] == []
    export = client.get("/api/memories/export").json()
    assert export["format"] == "jarvis-memory-v1" and export["memories"][0]["content"].endswith("chess.")

    changes = client.get("/api/memories/changes").json()
    assert [c["action"] for c in changes["changes"]] == ["saved", "updated"]
    assert client.get("/api/memories/changes", params={"after": changes["seq"]}).json()["changes"] == []

    assert client.delete(f"/api/memories/{memory_id}").status_code == 204
    assert client.delete(f"/api/memories/{memory_id}").status_code == 404
    client.post("/api/memories", json={"content": "Likes jazz.", "kind": "preference"})
    assert client.delete("/api/memories").json() == {"deleted": 1}


def test_learned_memory_shapes_the_next_conversation(client):
    with client:  # one event loop, so the background learning task can finish
        chat(client, "I'm studying chemistry for my exam next week")
        for _ in range(100):
            if client.get("/api/memories").json()["total"]:
                break
            import time

            time.sleep(0.02)
        memories = client.get("/api/memories").json()["memories"]
        assert memories and memories[0]["source"] == "learned"
        reply = chat(client, "what do you know about me?")[-1]["message"]["content"]
        assert "chemistry" in reply
        assert [c["action"] for c in client.get("/api/memories/changes").json()["changes"]] == ["learned"]


# ----- settings, keys, status ---------------------------------------------------------


def test_settings_endpoint_validates_and_reloads_models(client):
    boot = client.get("/api/bootstrap").json()
    assert boot["prefs"]["persona"]["wit"] == "subtle" and boot["greeting"].startswith("Good ")
    assert boot["options"]["persona"]["wit"] == ["off", "subtle", "playful"]

    updated = client.patch("/api/settings", json={"persona": {"wit": "off"}, "models": ["fake:demo", "fake:agent"]})
    assert updated.status_code == 200 and updated.json()["persona"]["wit"] == "off"
    assert client.get("/api/models").json()["ready"] == ["fake:demo", "fake:agent"]
    bad = client.patch("/api/settings", json={"persona": {"wit": "slapstick"}})
    assert bad.status_code == 422 and "wit must be one of" in bad.json()["detail"]

    tools = {tool["name"]: tool for tool in client.get("/api/tools").json()}
    assert tools["open_app"]["policy"] == "allow" and tools["recall"]["risk"] == "read"
    client.patch("/api/settings", json={"memory_enabled": False})
    assert {tool["name"]: tool for tool in client.get("/api/tools").json()}["remember"]["policy"] == "off"


def test_todo_api_persists_and_changes_status(client):
    created = client.post("/api/todos", json={"title": "Buy milk", "details": "Corner shop", "due_at": "2026-11-11T08:30:00+10:00"})
    assert created.status_code == 200
    todo_id = created.json()["id"]
    assert created.json()["due_at"] == "2026-11-10T22:30:00Z"
    assert client.get("/api/todos").json()[0]["title"] == "Buy milk"
    changed = client.patch(f"/api/todos/{todo_id}", json={"status": "completed"})
    assert changed.status_code == 200 and changed.json()["status"] == "completed"
    assert client.get("/api/todos?status=pending").json() == []


def test_adding_a_key_verifies_it_saves_it_and_selects_models(tmp_path, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    runtime = Runtime(make_settings(tmp_path, "groq:openai/gpt-oss-120b,groq:llama-3.1-8b-instant"), launcher=FakeLauncher())
    client = Client(runtime)
    seen = {}

    async def fake_listing(provider, key=None):
        seen["key"] = key
        if key == "gsk_wrong_key_0000":
            raise LLMError("rejected", status=401)
        return ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b", "whisper-large-v3-turbo"]

    monkeypatch.setattr(runtime, "list_provider_models", fake_listing)
    rejected = client.post("/api/keys", json={"provider": "groq", "key": "gsk_wrong_key_0000"})
    assert rejected.status_code == 422 and "rejected that key" in rejected.json()["detail"]
    assert not (tmp_path / ".env").exists() or "GROQ" not in (tmp_path / ".env").read_text()

    saved = client.post("/api/keys", json={"provider": "groq", "key": "  gsk_right_key_1234  "}).json()
    assert saved["ok"] and seen["key"] == "gsk_right_key_1234"
    # The retired default model was dropped in favour of ones this account can actually use.
    assert saved["models"] == ["groq:openai/gpt-oss-120b", "groq:openai/gpt-oss-20b", "groq:qwen/qwen3.8-27b"]
    assert "GROQ_API_KEY=gsk_right_key_1234" in (tmp_path / ".env").read_text()
    keys = client.get("/api/models").json()["keys"]
    assert keys["groq"] == {"set": True, "hint": "…1234"} and "gsk_right" not in client.get("/api/status").text

    assert client.delete("/api/keys/groq").json()["ready"] == []
    monkeypatch.delenv("GROQ_API_KEY", raising=False)


def test_status_and_model_check(client):
    chat(client, "open notepad")
    status = client.get("/api/status").json()
    assert status["models"][0]["model"] == "fake:agent" and status["models"][0]["usage"]["requests"] == 2
    assert status["database"]["conversations"] == 1 and status["database"]["search_index"] is True
    assert status["apps"]["backend"] == "test" and status["local_only"] is True
    (result,) = client.post("/api/models/check").json()
    assert result["ok"] and result["model"] == "fake:agent"
