from conftest import make_client, parse_sse


def chat(client, message, conversation_id=None):
    response = client.post("/api/chat", json={"message": message, "conversation_id": conversation_id})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    return parse_sse(response.text)


def test_health(client):
    data = client.get("/api/health").json()
    assert data["status"] == "ok"
    assert data["models"] == ["fake:echo"]


def test_serves_web_interface(client):
    page = client.get("/")
    assert page.status_code == 200 and "J.A.R.V.I.S." in page.text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/markdown.js").status_code == 200


def test_chat_creates_conversation_and_persists_both_messages(client):
    events = chat(client, "Hello JARVIS")
    types = [e["type"] for e in events]
    assert types[0] == "conversation" and types[1] == "model" and types[-1] == "done"
    assert "token" in types

    conversation_id = events[0]["conversation"]["id"]
    assert events[0]["conversation"]["title"] == "Hello JARVIS"
    reply_text = "".join(e["text"] for e in events if e["type"] == "token")
    assert "Hello JARVIS" in reply_text

    data = client.get(f"/api/conversations/{conversation_id}").json()
    assert [m["role"] for m in data["messages"]] == ["user", "assistant"]
    assert data["messages"][1]["content"] == reply_text
    assert data["messages"][1]["model"] == "fake:echo"


def test_follow_up_messages_share_a_conversation(client):
    first = chat(client, "One")
    conversation_id = first[0]["conversation"]["id"]
    chat(client, "Two", conversation_id)
    messages = client.get(f"/api/conversations/{conversation_id}").json()["messages"]
    assert [m["content"] for m in messages if m["role"] == "user"] == ["One", "Two"]
    assert len(client.get("/api/conversations").json()) == 1


def test_conversations_survive_a_restart(settings):
    first = make_client(settings)
    conversation_id = chat(first, "Persist this")[0]["conversation"]["id"]
    second = make_client(settings)  # new app instance, same database file
    assert second.get(f"/api/conversations/{conversation_id}").status_code == 200


def test_rename_and_delete(client):
    conversation_id = chat(client, "Rename me")[0]["conversation"]["id"]
    renamed = client.patch(f"/api/conversations/{conversation_id}", json={"title": "  Better   title "})
    assert renamed.json()["title"] == "Better title"
    assert client.delete(f"/api/conversations/{conversation_id}").status_code == 204
    assert client.get(f"/api/conversations/{conversation_id}").status_code == 404


def test_unknown_conversation_and_bad_input(client):
    assert client.post("/api/chat", json={"message": "hi", "conversation_id": "missing"}).status_code == 404
    assert client.post("/api/chat", json={"message": ""}).status_code == 422
    assert client.post("/api/chat", json={"message": "   "}).status_code == 422
    assert client.delete("/api/conversations/missing").status_code == 404


def test_fallback_model_answers_when_primary_fails(settings):
    client = make_client(settings, "fake:fail,fake:echo")
    events = chat(client, "Are you there?")
    assert [e for e in events if e["type"] == "model"][0]["model"] == "fake:echo"
    assert events[-1]["type"] == "done"


def test_error_event_when_every_model_fails(settings):
    client = make_client(settings, "fake:fail")
    events = chat(client, "Hello?")
    assert events[-1]["type"] == "error"
    assert "fake:fail" in events[-1]["message"]
    conversation_id = events[0]["conversation"]["id"]
    messages = client.get(f"/api/conversations/{conversation_id}").json()["messages"]
    assert [m["role"] for m in messages] == ["user"]  # no fake assistant reply stored


def test_missing_api_key_is_reported(settings):
    client = make_client(settings, "groq:openai/gpt-oss-120b")
    health = client.get("/api/health").json()
    assert health["status"] == "no_models"
    assert "GROQ_API_KEY" in health["skipped"][0]
    events = chat(client, "Hello?")
    assert events[-1]["type"] == "error" and "GROQ_API_KEY" in events[-1]["message"]
