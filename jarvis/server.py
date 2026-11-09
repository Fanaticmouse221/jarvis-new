"""HTTP API and web interface (FastAPI).

Endpoints
  GET    /                         the chat interface
  GET    /api/health               status and configured models
  GET    /api/conversations        list conversations (newest first)
  GET    /api/conversations/{id}   one conversation with its messages
  PATCH  /api/conversations/{id}   rename
  DELETE /api/conversations/{id}   delete
  POST   /api/chat                 send a message; reply streams back as Server-Sent Events
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from jarvis import __version__
from jarvis.chat import MAX_MESSAGE_CHARS, ChatService, ConversationNotFound
from jarvis.config import Settings
from jarvis.llm import ModelRouter
from jarvis.storage import Store

log = logging.getLogger("jarvis.server")

WEB_DIR = Path(__file__).parent / "web"


class ChatRequest(BaseModel):
    conversation_id: Optional[str] = None
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


class RenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


def _sse(event: dict[str, Any]) -> str:
    return f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


def create_app(
    settings: Settings | None = None,
    router: ModelRouter | None = None,
    store: Store | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    store = store or Store(settings.db_path)
    router = router or ModelRouter.from_settings(settings)
    service = ChatService(settings, store, router)

    app = FastAPI(title="JARVIS", version=__version__)
    app.state.settings = settings
    app.state.store = store
    app.state.router = router

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok" if router.providers else "no_models",
            "version": __version__,
            "models": router.labels,
            "skipped": router.skipped,
            "user_name": settings.user_name,
            "user_title": settings.user_title,
        }

    @app.get("/api/conversations")
    def list_conversations() -> list[dict[str, Any]]:
        return store.list_conversations()

    @app.get("/api/conversations/{conversation_id}")
    def get_conversation(conversation_id: str) -> dict[str, Any]:
        conversation = store.get_conversation(conversation_id)
        if conversation is None:
            raise HTTPException(404, "Conversation not found.")
        return {"conversation": conversation, "messages": store.get_messages(conversation_id)}

    @app.patch("/api/conversations/{conversation_id}")
    def rename_conversation(conversation_id: str, body: RenameRequest) -> dict[str, Any]:
        title = " ".join(body.title.split())
        if not title or not store.rename_conversation(conversation_id, title):
            raise HTTPException(404, "Conversation not found.")
        return store.get_conversation(conversation_id) or {}

    @app.delete("/api/conversations/{conversation_id}", status_code=204)
    def delete_conversation(conversation_id: str) -> Response:
        if not store.delete_conversation(conversation_id):
            raise HTTPException(404, "Conversation not found.")
        return Response(status_code=204)

    @app.post("/api/chat")
    async def chat(body: ChatRequest) -> StreamingResponse:
        try:
            conversation = service.start_turn(body.conversation_id, body.message)
        except ConversationNotFound:
            raise HTTPException(404, "Conversation not found.")
        except ValueError as exc:
            raise HTTPException(422, str(exc))

        async def events() -> AsyncIterator[str]:
            async for event in service.stream_reply(conversation):
                yield _sse(event)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    return app
