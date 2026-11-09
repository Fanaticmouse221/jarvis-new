import asyncio
import json

import httpx
import pytest

from jarvis.config import Settings, parse_model_list
from jarvis.llm import AllModelsFailed, ChatMessage, LLMError, ModelRouter, NoModelsAvailable
from jarvis.llm.fake import FakeProvider
from jarvis.llm.openai_compat import OpenAICompatProvider
from jarvis.llm.router import build_provider


def run(coro):
    return asyncio.run(coro)


async def collect(agen):
    return [item async for item in agen]


def sse_body(*chunks: dict, done: bool = True) -> bytes:
    lines = [f"data: {json.dumps(c)}\n\n" for c in chunks]
    if done:
        lines.append("data: [DONE]\n\n")
    return "".join(lines).encode()


def provider_with(handler) -> OpenAICompatProvider:
    return OpenAICompatProvider(
        provider="groq",
        base_url="https://api.example.test/v1/",
        model="openai/gpt-oss-120b",
        api_key="secret",
        max_tokens=100,
        extra_body={"reasoning_effort": "low"},
        transport=httpx.MockTransport(handler),
    )


MESSAGES = [ChatMessage("system", "Be brief."), ChatMessage("user", "Hi")]


def test_streams_content_and_ignores_reasoning():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        body = sse_body(
            {"choices": [{"delta": {"role": "assistant"}}]},
            {"choices": [{"delta": {"reasoning": "thinking..."}}]},
            {"choices": [{"delta": {"content": "Good "}}]},
            {"choices": [{"delta": {"content": "evening."}}]},
        )
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    chunks = run(collect(provider_with(handler).stream_chat(MESSAGES)))
    assert "".join(chunks) == "Good evening."
    assert seen["url"] == "https://api.example.test/v1/chat/completions"
    assert seen["auth"] == "Bearer secret"
    assert seen["body"]["stream"] is True
    assert seen["body"]["max_tokens"] == 100
    assert seen["body"]["reasoning_effort"] == "low"
    assert seen["body"]["messages"][1] == {"role": "user", "content": "Hi"}


@pytest.mark.parametrize("status,hint", [(401, "API key"), (404, "jarvis check"), (429, "rate limit")])
def test_http_errors_become_helpful_llm_errors(status, hint):
    def handler(request):
        return httpx.Response(status, json={"error": {"message": "upstream says no"}})

    with pytest.raises(LLMError) as info:
        run(collect(provider_with(handler).stream_chat(MESSAGES)))
    assert info.value.status == status
    assert hint in str(info.value)
    assert "upstream says no" in str(info.value)


def test_connection_failure_becomes_llm_error():
    def handler(request):
        raise httpx.ConnectError("no route")

    with pytest.raises(LLMError, match="Could not reach"):
        run(collect(provider_with(handler).stream_chat(MESSAGES)))


def test_list_models():
    def handler(request):
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json={"data": [{"id": "b-model"}, {"id": "models/a-model"}]})

    assert run(provider_with(handler).list_models()) == ["a-model", "b-model"]


def test_router_falls_back_before_first_token():
    router = ModelRouter([FakeProvider("fail"), FakeProvider("empty"), FakeProvider("echo")])
    events = run(collect(router.stream_chat(MESSAGES)))
    assert events[0].kind == "model" and events[0].value == "fake:echo"
    assert "You said" in "".join(e.value for e in events if e.kind == "token")


def test_router_reports_all_failures():
    router = ModelRouter([FakeProvider("fail"), FakeProvider("empty")])
    with pytest.raises(AllModelsFailed) as info:
        run(collect(router.stream_chat(MESSAGES)))
    assert len(info.value.errors) == 2


def test_router_without_models_explains_why():
    settings = Settings(models=parse_model_list("groq:openai/gpt-oss-120b"), api_keys={})
    router = ModelRouter.from_settings(settings)
    assert router.providers == []
    assert "GROQ_API_KEY" in router.skipped[0]
    with pytest.raises(NoModelsAvailable, match="GROQ_API_KEY"):
        run(collect(router.stream_chat(MESSAGES)))


def test_build_provider_presets():
    settings = Settings(api_keys={"GROQ_API_KEY": "k", "GEMINI_API_KEY": "g"}, reasoning_effort="low")
    groq = build_provider(parse_model_list("groq:openai/gpt-oss-120b")[0], settings)
    assert groq.base_url == "https://api.groq.com/openai/v1"
    assert groq.extra_body == {"reasoning_effort": "low"}

    gemini = build_provider(parse_model_list("gemini:gemini-3.8-flash")[0], settings)
    assert gemini.base_url.startswith("https://generativelanguage.googleapis.com")
    assert gemini.extra_body == {}  # reasoning_effort only sent to gpt-oss models

    ollama = build_provider(parse_model_list("ollama:some-local-model")[0], settings)
    assert ollama.base_url == "http://localhost:11434/v1" and ollama.api_key is None

    with pytest.raises(ValueError, match="Unknown provider"):
        build_provider(parse_model_list("nonsense:model")[0], settings)
