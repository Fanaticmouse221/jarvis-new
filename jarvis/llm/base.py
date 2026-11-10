"""Shared types for language-model providers.

Every provider exposes the same small interface, so the rest of JARVIS never
cares whether the model runs on Groq, Google, OpenRouter or this computer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol


@dataclass(frozen=True)
class ToolCall:
    """A model's request to run a tool. `arguments` is the raw JSON text it produced."""

    id: str
    name: str
    arguments: str


@dataclass
class ChatMessage:
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None

    def to_api(self) -> dict[str, Any]:
        data: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            data["tool_calls"] = [
                {"id": call.id, "type": "function", "function": {"name": call.name, "arguments": call.arguments}}
                for call in self.tool_calls
            ]
        if self.role == "tool":
            data["tool_call_id"] = self.tool_call_id
        return data


@dataclass
class StreamEvent:
    """One item from a provider's reply stream."""

    kind: str  # "text" | "tool_call" | "usage" | "rate"
    text: str = ""
    tool_call: ToolCall | None = None
    data: dict[str, Any] | None = None


class LLMError(Exception):
    """A provider failed to produce a reply.

    status       HTTP status, if any
    retry_after  seconds the provider asked us to wait (rate limits)
    code         provider error code, e.g. "tool_use_failed"
    """

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        retry_after: float | None = None,
        code: str | None = None,
    ):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after
        self.code = code


class LLMProvider(Protocol):
    label: str  # e.g. "groq:openai/gpt-oss-120b"

    def stream_chat(
        self, messages: list[ChatMessage], tools: list[dict[str, Any]] | None = None
    ) -> AsyncIterator[StreamEvent]:
        """Yield the reply as events. Raises LLMError on failure."""
        ...

    async def list_models(self) -> list[str]:
        """Return model IDs available from this provider (best effort)."""
        ...
