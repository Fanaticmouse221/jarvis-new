"""A stand-in for an OpenAI-compatible provider (such as Groq), for end-to-end tests.

It speaks the real wire protocol (streaming chunks, fragmented tool calls, usage,
rate-limit headers, 401 and 429 responses), so JARVIS's real HTTP client is
exercised. The "brain" behind it is the scripted one from jarvis.llm.fake.

    uv run uvicorn tests.e2e.mock_openai:app --port 8799
"""

from __future__ import annotations

import json

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from jarvis.llm.base import ChatMessage, ToolCall
from jarvis.llm.fake import scripted_reply

VALID_KEY = "gsk_e2e_valid_key_123456"
MODELS = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b", "whisper-large-v3-turbo"]

app = FastAPI()
seen: list[dict] = []  # every chat request received, newest last
limited_once: set[str] = set()


def _authorised(request: Request) -> bool:
    return request.headers.get("authorization") == f"Bearer {VALID_KEY}"


@app.get("/v1/models")
def models(request: Request):
    if not _authorised(request):
        return JSONResponse({"error": {"message": "Invalid API Key", "code": "invalid_api_key"}}, status_code=401)
    return {"data": [{"id": model} for model in MODELS]}


@app.get("/_seen")
def seen_requests():
    return seen[-12:]


@app.post("/v1/chat/completions")
async def chat(request: Request):
    if not _authorised(request):
        return JSONResponse({"error": {"message": "Invalid API Key", "code": "invalid_api_key"}}, status_code=401)
    body = await request.json()
    seen.append(body)
    messages = [
        ChatMessage(
            m["role"],
            m.get("content") or "",
            [ToolCall(c["id"], c["function"]["name"], c["function"]["arguments"]) for c in m.get("tool_calls") or []],
            m.get("tool_call_id"),
        )
        for m in body["messages"]
    ]
    last_user = next((m.content for m in reversed(messages) if m.role == "user"), "")
    if "rate limit test" in last_user.lower() and body["model"] not in limited_once and body["model"].endswith("120b"):
        limited_once.add(body["model"])
        return JSONResponse(
            {"error": {"message": "Rate limit reached. Please try again in 20s.", "code": "rate_limit_exceeded"}},
            status_code=429,
            headers={"retry-after": "20"},
        )
    text, calls = scripted_reply(messages, body.get("tools"))

    def chunk(delta: dict, **extra) -> str:
        return "data: " + json.dumps({"choices": [{"index": 0, "delta": delta}], **extra}) + "\n\n"

    async def stream():
        yield chunk({"role": "assistant"})
        yield chunk({"reasoning": "(hidden reasoning that must not be shown)"})
        for start in range(0, len(text), 9):
            yield chunk({"content": text[start : start + 9]})
        for index, call in enumerate(calls):
            half = len(call.arguments) // 2
            yield chunk({"tool_calls": [{"index": index, "id": call.id, "type": "function", "function": {"name": call.name, "arguments": ""}}]})
            yield chunk({"tool_calls": [{"index": index, "function": {"arguments": call.arguments[:half]}}]})
            yield chunk({"tool_calls": [{"index": index, "function": {"arguments": call.arguments[half:]}}]})
        prompt_tokens = sum(len(m.content) for m in messages) // 4
        yield "data: " + json.dumps({"choices": [], "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": len(text) // 4}}) + "\n\n"
        yield "data: [DONE]\n\n"

    headers = {
        "x-ratelimit-limit-requests": "1000",
        "x-ratelimit-remaining-requests": str(1000 - len(seen)),
        "x-ratelimit-limit-tokens": "8000",
        "x-ratelimit-remaining-tokens": "6400",
        "x-ratelimit-reset-tokens": "12s",
    }
    return StreamingResponse(stream(), media_type="text/event-stream", headers=headers)
