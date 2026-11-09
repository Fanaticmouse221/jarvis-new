"""Conversation orchestration: history -> context -> model -> storage.

This is the seam where later phases plug in: memory retrieval (Phase 3) will
add relevant facts to the context, and tools (Phase 4) will let the model act.
"""

from __future__ import annotations

from contextlib import aclosing
from typing import Any, AsyncIterator

from jarvis.config import Settings
from jarvis.llm import ChatMessage, LLMError, ModelRouter
from jarvis.persona import build_system_prompt
from jarvis.storage import Store

MAX_MESSAGE_CHARS = 20_000
TITLE_CHARS = 60


class ConversationNotFound(Exception):
    pass


def make_title(text: str) -> str:
    """A conversation title from the first message: its first line, trimmed."""
    first_line = " ".join(text.strip().splitlines()[0].split()) if text.strip() else ""
    if len(first_line) <= TITLE_CHARS:
        return first_line or "New conversation"
    return first_line[: TITLE_CHARS - 1].rstrip() + "…"


class ChatService:
    def __init__(self, settings: Settings, store: Store, router: ModelRouter):
        self.settings = settings
        self.store = store
        self.router = router

    def build_context(self, conversation_id: str) -> list[ChatMessage]:
        """System prompt plus the most recent history that fits the configured limits."""
        history = self.store.get_messages(conversation_id)
        selected: list[dict[str, Any]] = []
        total_chars = 0
        for message in reversed(history):
            if len(selected) >= self.settings.max_history_messages:
                break
            size = len(message["content"])
            if selected and total_chars + size > self.settings.max_context_chars:
                break
            selected.append(message)
            total_chars += size
        selected.reverse()
        # Conversations sent to a model should start with the user speaking.
        while selected and selected[0]["role"] != "user":
            selected.pop(0)

        context = [ChatMessage("system", build_system_prompt(self.settings))]
        context += [ChatMessage(m["role"], m["content"]) for m in selected]
        return context

    def start_turn(self, conversation_id: str | None, text: str) -> dict[str, Any]:
        """Validate the message, create the conversation if needed, and store the message."""
        text = text.strip()
        if not text:
            raise ValueError("Message is empty.")
        if len(text) > MAX_MESSAGE_CHARS:
            raise ValueError(f"Message is too long (limit {MAX_MESSAGE_CHARS:,} characters).")

        if conversation_id:
            conversation = self.store.get_conversation(conversation_id)
            if conversation is None:
                raise ConversationNotFound(conversation_id)
        else:
            conversation = self.store.create_conversation(make_title(text))

        self.store.add_message(conversation["id"], "user", text)
        return self.store.get_conversation(conversation["id"]) or conversation

    def _save_reply(self, conversation_id: str, text: str, model: str | None) -> dict[str, Any]:
        return self.store.add_message(conversation_id, "assistant", text, model)

    async def stream_reply(self, conversation: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
        """Stream JARVIS's reply as events: conversation, model, token..., then done or error."""
        conversation_id = conversation["id"]
        yield {"type": "conversation", "conversation": conversation}

        parts: list[str] = []
        model: str | None = None
        saved = False
        try:
            try:
                context = self.build_context(conversation_id)
                async with aclosing(self.router.stream_chat(context)) as stream:
                    async for event in stream:
                        if event.kind == "model":
                            model = event.value
                            yield {"type": "model", "model": model}
                        else:
                            parts.append(event.value)
                            yield {"type": "token", "text": event.value}
            except LLMError as exc:
                if parts:
                    self._save_reply(conversation_id, "".join(parts) + "\n\n*[Response interrupted]*", model)
                    saved = True
                yield {"type": "error", "message": str(exc)}
                return

            message = self._save_reply(conversation_id, "".join(parts), model)
            saved = True
            yield {"type": "done", "message": message}
        finally:
            # Reached without saving if the user pressed Stop mid-reply.
            if not saved and parts:
                self._save_reply(conversation_id, "".join(parts) + "\n\n*[Stopped]*", model)
