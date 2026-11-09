"""Shared types for language-model providers.

Every provider exposes the same small interface, so the rest of JARVIS never
cares whether the model runs on Groq, Google, OpenRouter or this computer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Protocol


@dataclass(frozen=True)
class ChatMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


class LLMError(Exception):
    """A provider failed to produce a reply. `status` is the HTTP status, if any."""

    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


class LLMProvider(Protocol):
    label: str  # e.g. "groq:openai/gpt-oss-120b"

    def stream_chat(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        """Yield the reply as text chunks. Raises LLMError on failure."""
        ...

    async def list_models(self) -> list[str]:
        """Return model IDs available from this provider (best effort)."""
        ...
