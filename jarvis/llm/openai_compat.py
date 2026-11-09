"""Provider for any OpenAI-compatible Chat Completions API.

Groq, Google Gemini, OpenRouter, Ollama (local) and many others all speak this
same protocol, so one small client covers them all. Uses httpx directly rather
than a vendor SDK: fewer dependencies and full control over streaming and errors.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

import httpx

from jarvis.llm.base import ChatMessage, LLMError

_HINTS = {
    401: "the API key was rejected. Check it in your .env file.",
    403: "access was refused. Check the API key and that this model is available to your account.",
    404: "model or endpoint not found. Run `uv run jarvis check` to list available models.",
    413: "the request was too large. Try a new conversation or lower JARVIS_MAX_CONTEXT_CHARS.",
    429: "rate limit reached on the free tier. Wait a minute, or add a fallback model.",
}


def _error_detail(body: str) -> str:
    """Pull a readable message out of an error response body."""
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return body.strip()[:300]
    if isinstance(data, list) and data:
        data = data[0]
    if isinstance(data, dict):
        err = data.get("error", data)
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])[:300]
        if isinstance(err, str):
            return err[:300]
    return body.strip()[:300]


class OpenAICompatProvider:
    def __init__(
        self,
        *,
        provider: str,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout: float = 90.0,
        max_tokens: int | None = None,
        temperature: float | None = None,
        extra_body: dict[str, Any] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.provider = provider
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.extra_body = extra_body or {}
        self._transport = transport  # injectable for tests
        self.label = f"{provider}:{model}"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _client(self) -> httpx.AsyncClient:
        timeout = httpx.Timeout(self.timeout, connect=15.0)
        return httpx.AsyncClient(timeout=timeout, transport=self._transport)

    def _fail(self, status: int, body: str) -> LLMError:
        hint = _HINTS.get(status) or ("the service is having problems." if status >= 500 else "")
        detail = _error_detail(body)
        message = f"{self.label} returned HTTP {status}"
        if hint:
            message += f": {hint}"
        if detail:
            message += f" (Details: {detail})"
        return LLMError(message, status=status)

    async def stream_chat(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": True,
        }
        if self.max_tokens:
            payload["max_tokens"] = self.max_tokens
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        payload.update(self.extra_body)

        try:
            async with self._client() as client:
                async with client.stream(
                    "POST", f"{self.base_url}/chat/completions", json=payload, headers=self._headers()
                ) as response:
                    if response.status_code != 200:
                        body = (await response.aread()).decode("utf-8", errors="replace")
                        raise self._fail(response.status_code, body)

                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line.startswith("data:"):
                            continue  # blank lines, SSE comments, event names
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(chunk, dict) and chunk.get("error"):
                            raise LLMError(f"{self.label} error: {_error_detail(data)}")
                        for choice in chunk.get("choices") or []:
                            # Only `content` is the answer. Reasoning models (e.g. gpt-oss)
                            # may also stream `reasoning`, which is deliberately ignored.
                            text = (choice.get("delta") or {}).get("content")
                            if text:
                                yield text
        except httpx.TimeoutException as exc:
            raise LLMError(f"{self.label} timed out after {self.timeout:.0f}s.") from exc
        except httpx.HTTPError as exc:
            raise LLMError(
                f"Could not reach {self.label} ({type(exc).__name__}). Check your internet connection."
            ) from exc

    async def list_models(self) -> list[str]:
        try:
            async with self._client() as client:
                response = await client.get(f"{self.base_url}/models", headers=self._headers())
        except httpx.HTTPError as exc:
            raise LLMError(f"Could not reach {self.label} to list models.") from exc
        if response.status_code != 200:
            raise self._fail(response.status_code, response.text)
        data = response.json().get("data", [])
        ids = [str(item.get("id", "")).removeprefix("models/") for item in data if item.get("id")]
        return sorted(ids)
