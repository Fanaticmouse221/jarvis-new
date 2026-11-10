"""Provider for any OpenAI-compatible Chat Completions API.

Groq, Google Gemini, OpenRouter, Ollama (local) and many others all speak this
same protocol, so one small client covers them all. Uses httpx directly rather
than a vendor SDK: fewer dependencies and full control over streaming, tool
calls, rate-limit headers and error messages.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, AsyncIterator

import httpx

from jarvis.llm.base import ChatMessage, LLMError, StreamEvent, ToolCall

_HINTS = {
    401: "the API key was rejected. Check it in Settings.",
    403: "access was refused. Check the API key and that this model is available to your account.",
    404: "this model wasn't found. It may have been retired; pick another in Settings.",
    413: "the request was too large for this model's limit.",
    429: "rate limit reached on the free tier.",
}

_RATE_HEADERS = {
    "x-ratelimit-limit-requests": "limit_requests",
    "x-ratelimit-remaining-requests": "remaining_requests",
    "x-ratelimit-reset-requests": "reset_requests",
    "x-ratelimit-limit-tokens": "limit_tokens",
    "x-ratelimit-remaining-tokens": "remaining_tokens",
    "x-ratelimit-reset-tokens": "reset_tokens",
}


def _error_fields(body: str) -> tuple[str, str | None]:
    """Pull a readable message and an error code out of an error response body."""
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, ValueError):
        return body.strip()[:300], None
    if isinstance(data, list) and data:
        data = data[0]
    if isinstance(data, dict):
        err = data.get("error", data)
        if isinstance(err, dict):
            code = err.get("code")
            return str(err.get("message") or "")[:300], str(code) if code else None
        if isinstance(err, str):
            return err[:300], None
    return body.strip()[:300], None


def _retry_after(headers: httpx.Headers, message: str) -> float | None:
    raw = headers.get("retry-after")
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    # Groq also says e.g. "Please try again in 7.66s" or "in 1m2.5s" in the message.
    match = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", message)
    if match:
        return int(match.group(1) or 0) * 60 + float(match.group(2))
    return None


def parse_rate_headers(headers: httpx.Headers) -> dict[str, Any]:
    """Rate-limit state from response headers (Groq's naming; ignored if absent)."""
    rate: dict[str, Any] = {}
    for header, key in _RATE_HEADERS.items():
        value = headers.get(header)
        if value is None:
            continue
        if key.startswith("reset"):
            rate[key] = value
        else:
            try:
                rate[key] = int(float(value))
            except ValueError:
                pass
    return rate


class _UnsupportedOption(Exception):
    """The provider refused an optional request field (internal; handled by a retry)."""

    def __init__(self, option: str):
        super().__init__(option)
        self.option = option


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
        stream_usage: bool = True,
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
        self.stream_usage = stream_usage
        self._transport = transport  # injectable for tests
        self.label = f"{provider}:{model}"

    def _headers(self, json_body: bool = True) -> dict[str, str]:
        headers = {"Content-Type": "application/json"} if json_body else {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _client(self) -> httpx.AsyncClient:
        timeout = httpx.Timeout(self.timeout, connect=15.0)
        return httpx.AsyncClient(timeout=timeout, transport=self._transport)

    def _fail(self, status: int, body: str, headers: httpx.Headers) -> LLMError:
        detail, code = _error_fields(body)
        hint = _HINTS.get(status) or ("the service is having problems." if status >= 500 else "")
        if code == "tool_use_failed":
            hint = "the model produced an invalid tool call."
        message = f"{self.label} returned HTTP {status}"
        if hint:
            message += f": {hint}"
        if detail:
            message += f" (Details: {detail})"
        retry = _retry_after(headers, detail) if status == 429 else None
        return LLMError(message, status=status, retry_after=retry, code=code)

    @staticmethod
    def _merge_tool_delta(slots: list[dict[str, str]], by_index: dict[int, dict[str, str]], item: dict[str, Any]) -> None:
        """Tool calls arrive in fragments; stitch them together by index (or id)."""
        index = item.get("index")
        slot: dict[str, str] | None = None
        if index is not None:
            slot = by_index.get(index)
        elif slots and not item.get("id"):
            slot = slots[-1]
        elif slots and item.get("id") == slots[-1]["id"]:
            slot = slots[-1]
        if slot is None:
            slot = {"id": "", "name": "", "arguments": ""}
            slots.append(slot)
            if index is not None:
                by_index[index] = slot
        function = item.get("function") or {}
        if item.get("id"):
            slot["id"] = item["id"]
        if function.get("name"):
            slot["name"] = function["name"]
        if function.get("arguments"):
            slot["arguments"] += function["arguments"]

    async def stream_chat(
        self, messages: list[ChatMessage], tools: list[dict[str, Any]] | None = None
    ) -> AsyncIterator[StreamEvent]:
        for _ in range(4):
            try:
                async for event in self._stream_once(messages, tools):
                    yield event
                return
            except _UnsupportedOption as unsupported:
                # The provider rejected an optional extra before sending anything. Drop it for
                # good and ask again, so one provider's quirk never stops JARVIS answering.
                if unsupported.option == "stream_options":
                    self.stream_usage = False
                else:
                    self.extra_body.pop(unsupported.option, None)
        raise LLMError(f"{self.label} kept rejecting the request.", status=400)

    def _unsupported_option(self, status: int, body: str) -> str | None:
        if status != 400:
            return None
        if self.stream_usage and "stream_options" in body:
            return "stream_options"
        return next((option for option in self.extra_body if option in body), None)

    async def _stream_once(
        self, messages: list[ChatMessage], tools: list[dict[str, Any]] | None
    ) -> AsyncIterator[StreamEvent]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [message.to_api() for message in messages],
            "stream": True,
        }
        if self.stream_usage:
            payload["stream_options"] = {"include_usage": True}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if self.max_tokens:
            payload["max_tokens"] = self.max_tokens
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        payload.update(self.extra_body)

        slots: list[dict[str, str]] = []
        by_index: dict[int, dict[str, str]] = {}
        try:
            async with self._client() as client:
                async with client.stream(
                    "POST", f"{self.base_url}/chat/completions", json=payload, headers=self._headers()
                ) as response:
                    if response.status_code != 200:
                        body = (await response.aread()).decode("utf-8", errors="replace")
                        option = self._unsupported_option(response.status_code, body)
                        if option:
                            raise _UnsupportedOption(option)
                        raise self._fail(response.status_code, body, response.headers)
                    rate = parse_rate_headers(response.headers)
                    if rate:
                        yield StreamEvent("rate", data=rate)

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
                        if not isinstance(chunk, dict):
                            continue
                        if chunk.get("error"):
                            detail, code = _error_fields(data)
                            raise LLMError(f"{self.label} error: {detail}", code=code)
                        usage = chunk.get("usage") or (chunk.get("x_groq") or {}).get("usage")
                        if usage:
                            yield StreamEvent(
                                "usage",
                                data={
                                    "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                                    "completion_tokens": int(usage.get("completion_tokens") or 0),
                                },
                            )
                        for choice in chunk.get("choices") or []:
                            delta = choice.get("delta") or {}
                            # Only `content` is the answer. Reasoning models (e.g. gpt-oss)
                            # also stream `reasoning`, which is deliberately ignored.
                            text = delta.get("content")
                            if text:
                                yield StreamEvent("text", text=text)
                            for item in delta.get("tool_calls") or []:
                                self._merge_tool_delta(slots, by_index, item)
        except httpx.TimeoutException as exc:
            raise LLMError(f"{self.label} timed out after {self.timeout:.0f}s.") from exc
        except httpx.HTTPError as exc:
            raise LLMError(
                f"Could not reach {self.label} ({type(exc).__name__}). Check your internet connection."
            ) from exc

        for slot in slots:
            if slot["name"]:
                yield StreamEvent(
                    "tool_call",
                    tool_call=ToolCall(
                        id=slot["id"] or f"call_{uuid.uuid4().hex[:12]}",
                        name=slot["name"],
                        arguments=slot["arguments"] or "{}",
                    ),
                )

    async def list_models(self) -> list[str]:
        try:
            async with self._client() as client:
                response = await client.get(f"{self.base_url}/models", headers=self._headers())
        except httpx.HTTPError as exc:
            raise LLMError(f"Could not reach {self.provider} to list models. Check your internet connection.") from exc
        if response.status_code != 200:
            raise self._fail(response.status_code, response.text, response.headers)
        data = response.json().get("data", [])
        ids = [str(item.get("id", "")).removeprefix("models/") for item in data if item.get("id")]
        return sorted(ids)
