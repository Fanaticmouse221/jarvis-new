import asyncio
import json

import httpx
import pytest

from jarvis.config import Settings, parse_model_list
from jarvis.llm import AllModelsFailed, ChatMessage, LLMError, ModelRouter, NoModelsAvailable, StreamEvent, ToolCall
from jarvis.llm.fake import FakeProvider
from jarvis.llm.openai_compat import OpenAICompatProvider
from jarvis.llm.router import build_provider
from jarvis.storage import Store

MESSAGES = [ChatMessage("system", "Be brief."), ChatMessage("user", "Hi")]
TOOLS = [{"type": "function", "function": {"name": "open_app", "description": "", "parameters": {"type": "object", "properties": {}}}}]


def collect(agen):
    async def go():
        return [item async for item in agen]

    return asyncio.run(go())


def sse_body(*chunks: dict) -> bytes:
    return ("".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n").encode()


def provider_with(handler) -> OpenAICompatProvider:
    return OpenAICompatProvider(
        provider="groq", base_url="https://api.example.test/v1/", model="openai/gpt-oss-120b", api_key="secret",
        max_tokens=100, extra_body={"reasoning_effort": "low"}, transport=httpx.MockTransport(handler),
    )


# ----- the HTTP provider ------------------------------------------------------


def test_streams_text_usage_and_rate_headers_and_ignores_reasoning():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"], seen["body"] = str(request.url), request.headers["authorization"], json.loads(request.content)
        body = sse_body(
            {"choices": [{"delta": {"role": "assistant"}}]},
            {"choices": [{"delta": {"reasoning": "thinking..."}}]},
            {"choices": [{"delta": {"content": "Good "}}]},
            {"choices": [{"delta": {"content": "evening."}}]},
            {"choices": [], "usage": {"prompt_tokens": 42, "completion_tokens": 7}},
        )
        headers = {"content-type": "text/event-stream", "x-ratelimit-remaining-requests": "998", "x-ratelimit-remaining-tokens": "7412", "x-ratelimit-reset-tokens": "4.4s"}
        return httpx.Response(200, content=body, headers=headers)

    events = collect(provider_with(handler).stream_chat(MESSAGES, TOOLS))
    assert "".join(e.text for e in events if e.kind == "text") == "Good evening."
    assert [e.data for e in events if e.kind == "usage"] == [{"prompt_tokens": 42, "completion_tokens": 7}]
    assert events[0].kind == "rate" and events[0].data == {"remaining_requests": 998, "remaining_tokens": 7412, "reset_tokens": "4.4s"}
    assert seen["url"] == "https://api.example.test/v1/chat/completions" and seen["auth"] == "Bearer secret"
    body = seen["body"]
    assert body["stream"] and body["max_tokens"] == 100 and body["reasoning_effort"] == "low"
    assert body["tools"] == TOOLS and body["tool_choice"] == "auto" and body["stream_options"] == {"include_usage": True}


def test_tool_calls_are_assembled_from_fragments():
    def handler(request):
        return httpx.Response(200, content=sse_body(
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_a", "function": {"name": "open_app", "arguments": ""}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "{\"name\": \"Spo"}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "tify\"}"}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 1, "id": "call_b", "function": {"name": "recall", "arguments": "{\"query\": \"music\"}"}}]}}]},
            {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
        ))

    calls = [e.tool_call for e in collect(provider_with(handler).stream_chat(MESSAGES, TOOLS)) if e.kind == "tool_call"]
    assert calls == [ToolCall("call_a", "open_app", '{"name": "Spotify"}'), ToolCall("call_b", "recall", '{"query": "music"}')]


def test_tool_messages_are_sent_in_api_format():
    sent = {}

    def handler(request):
        sent.update(json.loads(request.content))
        return httpx.Response(200, content=sse_body({"choices": [{"delta": {"content": "ok"}}]}))

    history = MESSAGES + [
        ChatMessage("assistant", "", tool_calls=[ToolCall("call_1", "open_app", '{"name": "Notepad"}')]),
        ChatMessage("tool", "Opened Notepad.", tool_call_id="call_1"),
    ]
    collect(provider_with(handler).stream_chat(history))
    assert sent["messages"][2]["tool_calls"][0] == {"id": "call_1", "type": "function", "function": {"name": "open_app", "arguments": '{"name": "Notepad"}'}}
    assert sent["messages"][3] == {"role": "tool", "content": "Opened Notepad.", "tool_call_id": "call_1"}
    assert "tools" not in sent


@pytest.mark.parametrize("status,hint", [(401, "API key"), (404, "retired"), (413, "too large")])
def test_http_errors_become_helpful_llm_errors(status, hint):
    def handler(request):
        return httpx.Response(status, json={"error": {"message": "upstream says no"}})

    with pytest.raises(LLMError) as info:
        collect(provider_with(handler).stream_chat(MESSAGES))
    assert info.value.status == status and hint in str(info.value) and "upstream says no" in str(info.value)


def test_rate_limit_and_tool_errors_carry_details():
    def limited(request):
        return httpx.Response(429, headers={"retry-after": "7"}, json={"error": {"message": "slow down", "code": "rate_limit_exceeded"}})

    def limited_in_text(request):
        return httpx.Response(429, json={"error": {"message": "Rate limit reached. Please try again in 1m2.5s."}})

    def garbled(request):
        return httpx.Response(400, json={"error": {"message": "bad call", "code": "tool_use_failed"}})

    for handler, retry in ((limited, 7.0), (limited_in_text, 62.5)):
        with pytest.raises(LLMError) as info:
            collect(provider_with(handler).stream_chat(MESSAGES))
        assert info.value.status == 429 and info.value.retry_after == retry
    with pytest.raises(LLMError) as info:
        collect(provider_with(garbled).stream_chat(MESSAGES))
    assert info.value.code == "tool_use_failed" and "invalid tool call" in str(info.value)


def test_optional_fields_a_provider_rejects_are_dropped_and_the_request_retried():
    bodies = []

    def picky(request):
        body = json.loads(request.content)
        bodies.append(body)
        if "stream_options" in body:
            return httpx.Response(400, json={"error": {"message": "unknown field: stream_options"}})
        if "reasoning_effort" in body:
            return httpx.Response(400, json={"error": {"message": "reasoning_effort is not supported by this model"}})
        return httpx.Response(200, content=sse_body({"choices": [{"delta": {"content": "Fine."}}]}))

    provider = provider_with(picky)
    assert "".join(e.text for e in collect(provider.stream_chat(MESSAGES)) if e.kind == "text") == "Fine."
    assert len(bodies) == 3 and "stream_options" not in bodies[-1] and "reasoning_effort" not in bodies[-1]
    assert provider.stream_usage is False and provider.extra_body == {}


def test_connection_failure_and_model_listing():
    def down(request):
        raise httpx.ConnectError("no route")

    def models(request):
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json={"data": [{"id": "b-model"}, {"id": "models/a-model"}]})

    with pytest.raises(LLMError, match="Could not reach"):
        collect(provider_with(down).stream_chat(MESSAGES))
    assert asyncio.run(provider_with(models).list_models()) == ["a-model", "b-model"]


# ----- the router -------------------------------------------------------------


def test_router_falls_back_before_first_output_and_records_usage(tmp_path):
    store = Store(tmp_path / "t.db")
    router = ModelRouter([FakeProvider("fail"), FakeProvider("empty"), FakeProvider("agent")], store=store)
    events = collect(router.stream_chat(MESSAGES))
    assert events[0].kind == "model" and events[0].value == "fake:agent"
    usage = {row["model"]: row for row in store.usage_for_day()}
    assert usage["fake:fail"]["errors"] == 1 and usage["fake:agent"]["requests"] == 1 and usage["fake:agent"]["errors"] == 0


def test_router_prefers_requested_model():
    router = ModelRouter([FakeProvider("echo"), FakeProvider("agent")])
    assert collect(router.stream_chat(MESSAGES, prefer="fake:agent"))[0].value == "fake:agent"


def test_router_rests_a_rate_limited_model_then_retries():
    limited = FakeProvider("ratelimit")
    router = ModelRouter([limited])
    with pytest.raises(AllModelsFailed):
        collect(router.stream_chat(MESSAGES))
    assert len(limited.calls) == 2  # tried, waited the 0.05 s it was told to, tried again

    # With a healthy fallback there is no waiting: it answers at once and the limited model rests.
    router = ModelRouter([FakeProvider("ratelimit"), FakeProvider("echo")])
    events = collect(router.stream_chat(MESSAGES))
    assert events[0].value == "fake:echo" and not [e for e in events if e.kind == "status"]


def test_router_waits_when_every_model_is_resting():
    flaky = FakeProvider("script", script=[])
    calls = {"n": 0}

    async def stream_chat(messages, tools=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise LLMError("limited", status=429, retry_after=0.05)
        yield StreamEvent("text", text="Back online.")

    flaky.stream_chat = stream_chat
    events = collect(ModelRouter([flaky]).stream_chat(MESSAGES))
    assert [e.kind for e in events] == ["status", "model", "token"]
    assert "Rate limit reached" in events[0].value


def test_router_retries_a_garbled_tool_call_once():
    provider = FakeProvider("script")
    attempts = {"n": 0}

    async def stream_chat(messages, tools=None):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise LLMError("bad tool call", status=400, code="tool_use_failed")
        yield StreamEvent("text", text="Second time lucky.")

    provider.stream_chat = stream_chat
    events = collect(ModelRouter([provider]).stream_chat(MESSAGES))
    assert attempts["n"] == 2 and events[-1].value == "Second time lucky."


def test_router_limits_and_missing_keys(tmp_path):
    store = Store(tmp_path / "t.db")
    store.record_usage("fake:echo")
    with pytest.raises(LLMError, match="request limit"):
        collect(ModelRouter([FakeProvider("echo")], store=store, daily_limit=1).stream_chat(MESSAGES))

    router = ModelRouter.from_settings(Settings(models=parse_model_list("groq:openai/gpt-oss-120b"), api_keys={}))
    assert router.providers == [] and "API key" in router.skipped[0]
    with pytest.raises(NoModelsAvailable, match="API key"):
        collect(router.stream_chat(MESSAGES))


def test_build_provider_presets():
    settings = Settings(api_keys={"GROQ_API_KEY": "k", "GEMINI_API_KEY": "g"})
    groq = build_provider(parse_model_list("groq:openai/gpt-oss-120b")[0], settings, "medium")
    assert groq.base_url == "https://api.groq.com/openai/v1" and groq.extra_body == {"reasoning_effort": "medium"}
    gemini = build_provider(parse_model_list("gemini:some-flash-model")[0], settings)
    assert gemini.base_url.startswith("https://generativelanguage.googleapis.com") and gemini.extra_body == {}
    ollama = build_provider(parse_model_list("ollama:some-local-model")[0], settings)
    assert ollama.base_url == "http://localhost:11434/v1" and ollama.api_key is None
    with pytest.raises(ValueError, match="Unknown provider"):
        build_provider(parse_model_list("nonsense:model")[0], settings)
