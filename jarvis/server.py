"""HTTP API and web interface (FastAPI).

Every /api route is protected by `guard` (see below). The interface is plain
static files served from `web/`.

  GET    /                              the interface
  GET    /api/bootstrap                 everything the interface needs at start-up
  GET    /api/settings  PATCH           preferences (personality, models, permissions)
  POST   /api/keys      DELETE /{p}     add or remove a provider API key
  GET    /api/models/available          models a provider offers
  POST   /api/models/check              test each configured model
  GET    /api/conversations ...         list / search / read / rename / delete / export
  POST   /api/chat                      send a message; events stream back (SSE)
  POST   /api/approvals/{id}            approve or decline a waiting action
  GET    /api/memories ...              list / search / add / edit / delete / export / changes
  GET    /api/activity                  the action log
  GET    /api/tools                     tools and their permissions
  GET    /api/status                    health of every subsystem
  POST   /api/shutdown                  stop JARVIS
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import signal
import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from jarvis import __version__
from jarvis.agent import MAX_MESSAGE_CHARS, ConversationNotFound
from jarvis.config import Settings
from jarvis.llm import LLMError
from jarvis.persona import greeting
from jarvis.prefs import PERSONA_OPTIONS
from jarvis.runtime import Runtime
from jarvis.storage import MEMORY_KINDS
from jarvis.telegram import TelegramError
from jarvis.tools import GROUPS

log = logging.getLogger("jarvis.server")

WEB_DIR = Path(__file__).parent / "web"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]", "testserver"}


class ChatRequest(BaseModel):
    conversation_id: Optional[str] = None
    message: str = Field(default="", max_length=MAX_MESSAGE_CHARS)
    model: Optional[str] = Field(default=None, max_length=160)
    regenerate: bool = False
    edit_message_id: Optional[int] = None


class RenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class KeyRequest(BaseModel):
    provider: str
    key: str = Field(min_length=1, max_length=400)


class ApprovalRequest(BaseModel):
    approve: bool
    always: bool = False


class TelegramTokenRequest(BaseModel):
    token: str = Field(min_length=20, max_length=300)


class MemoryCreate(BaseModel):
    content: str
    kind: str = "note"


class MemoryUpdate(BaseModel):
    content: Optional[str] = None
    kind: Optional[str] = None
    pinned: Optional[bool] = None


def _sse(event: dict[str, Any]) -> str:
    return f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


def _hostname(host_header: str) -> str:
    host = host_header.strip().lower()
    if host.startswith("["):
        return host.split("]")[0] + "]"
    return host.rsplit(":", 1)[0] if ":" in host else host


def create_app(settings: Settings | None = None, runtime: Runtime | None = None) -> FastAPI:
    settings = settings or (runtime.settings if runtime else Settings.from_env())
    rt = runtime or Runtime(settings)
    local_only = settings.host in ("127.0.0.1", "localhost", "::1")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await rt.start()
        try:
            yield
        finally:
            await rt.stop()

    app = FastAPI(title="JARVIS", version=__version__, docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.runtime = rt

    def guard(request: Request) -> None:
        """Only this app's own interface may call the API.

        JARVIS can act on the computer, so a web page open in another tab must
        not be able to reach it. Three checks: the request is addressed to this
        machine (blocks DNS rebinding), it doesn't come from another site's
        page, and it carries the secret token that only our own page is given.
        """
        if local_only and _hostname(request.headers.get("host", "")) not in LOCAL_HOSTS:
            raise HTTPException(403, "Unexpected Host header.")
        origin = request.headers.get("origin")
        if origin and urlparse(origin).netloc != request.headers.get("host", ""):
            raise HTTPException(403, "Cross-site requests are not allowed.")
        if not secrets.compare_digest(request.headers.get("x-jarvis-token", ""), rt.token):
            raise HTTPException(401, "Missing or invalid session token. Reload the page.")

    api = APIRouter(prefix="/api", dependencies=[Depends(guard)])

    # ----- start-up data, settings, keys, models ---------------------------

    def tools_payload() -> list[dict[str, Any]]:
        prefs = rt.prefs.all()
        return [
            {
                "name": tool.name,
                "label": tool.label,
                "group": GROUPS.get(tool.group, tool.group),
                "description": tool.description,
                "risk": tool.risk,
                "policy": rt.registry.policy(tool, prefs),
                "locked": tool.risk == "sensitive",
            }
            for tool in rt.registry.all()
        ]

    def models_payload() -> dict[str, Any]:
        return {"ready": rt.router.labels, "skipped": rt.router.skipped, "keys": rt.key_status()}

    @api.get("/bootstrap")
    def bootstrap() -> dict[str, Any]:
        prefs = rt.prefs.all()
        recent = rt.store.list_conversations(limit=1)
        return {
            "version": __version__,
            "prefs": prefs,
            "models": models_payload(),
            "greeting": greeting(title=prefs["user_title"]),
            "last_conversation": recent[0] if recent else None,
            "memory_count": rt.store.counts()["memories"],
            "change_seq": rt.change_seq,
            "options": {"persona": PERSONA_OPTIONS, "memory_kinds": MEMORY_KINDS},
            "platform": sys.platform,
        }

    @api.get("/settings")
    def get_settings() -> dict[str, Any]:
        return rt.prefs.all()

    @api.patch("/settings")
    async def patch_settings(request: Request) -> dict[str, Any]:
        try:
            return rt.update_prefs(await request.json())
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    @api.post("/keys")
    async def add_key(body: KeyRequest) -> dict[str, Any]:
        try:
            return await rt.set_key(body.provider, body.key)
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    @api.delete("/keys/{provider}")
    def delete_key(provider: str) -> dict[str, Any]:
        try:
            rt.remove_key(provider)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        return models_payload()

    @api.get("/models")
    def get_models() -> dict[str, Any]:
        return models_payload()

    @api.get("/models/available")
    async def available_models(provider: str = "groq") -> dict[str, Any]:
        if provider == "fake":
            return {"provider": provider, "models": ["agent", "demo"]}
        try:
            return {"provider": provider, "models": await rt.list_provider_models(provider)}
        except (LLMError, ValueError) as exc:
            raise HTTPException(502, str(exc))

    @api.post("/models/check")
    async def check_models() -> list[dict[str, Any]]:
        return await rt.check_models()

    # ----- conversations ---------------------------------------------------

    @api.get("/telegram")
    def telegram_state() -> dict[str, Any]:
        return rt.telegram.status()

    @api.post("/telegram/token")
    async def telegram_token(body: TelegramTokenRequest) -> dict[str, Any]:
        try:
            return await rt.set_telegram_token(body.token)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        except TelegramError as exc:
            raise HTTPException(502, str(exc))

    @api.post("/telegram/unlink")
    async def telegram_unlink() -> dict[str, Any]:
        await rt.telegram.unlink()
        return rt.telegram.status()

    @api.post("/telegram/test")
    async def telegram_test() -> dict[str, Any]:
        try:
            await rt.telegram.test_message()
            return {"ok": True}
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        except TelegramError as exc:
            raise HTTPException(502, str(exc))

    @api.delete("/telegram")
    async def telegram_remove() -> dict[str, Any]:
        return await rt.remove_telegram()

    @api.get("/conversations")
    def list_conversations(q: str = "") -> list[dict[str, Any]]:
        return rt.store.list_conversations(query=q)

    @api.delete("/conversations")
    def delete_all_conversations() -> dict[str, int]:
        return {"deleted": rt.store.delete_all_conversations()}

    @api.get("/conversations/{conversation_id}")
    def get_conversation(conversation_id: str) -> dict[str, Any]:
        conversation = rt.store.get_conversation(conversation_id)
        if conversation is None:
            raise HTTPException(404, "Conversation not found.")
        return {"conversation": conversation, "messages": rt.store.get_messages(conversation_id)}

    @api.patch("/conversations/{conversation_id}")
    def rename_conversation(conversation_id: str, body: RenameRequest) -> dict[str, Any]:
        title = " ".join(body.title.split())
        if not title or not rt.store.rename_conversation(conversation_id, title):
            raise HTTPException(404, "Conversation not found.")
        return rt.store.get_conversation(conversation_id) or {}

    @api.delete("/conversations/{conversation_id}", status_code=204)
    def delete_conversation(conversation_id: str) -> Response:
        if not rt.store.delete_conversation(conversation_id):
            raise HTTPException(404, "Conversation not found.")
        return Response(status_code=204)

    @api.get("/conversations/{conversation_id}/export")
    def export_conversation(conversation_id: str) -> PlainTextResponse:
        conversation = rt.store.get_conversation(conversation_id)
        if conversation is None:
            raise HTTPException(404, "Conversation not found.")
        lines = [f"# {conversation['title']}", ""]
        for message in rt.store.get_messages(conversation_id):
            lines += [f"**{'You' if message['role'] == 'user' else 'JARVIS'}**", "", message["content"], ""]
        return PlainTextResponse("\n".join(lines), media_type="text/markdown; charset=utf-8")

    # ----- chat ------------------------------------------------------------

    @api.post("/chat")
    async def chat(body: ChatRequest) -> StreamingResponse:
        if body.conversation_id and body.conversation_id in rt.active:
            raise HTTPException(409, "JARVIS is still answering in this conversation.")
        try:
            conversation = rt.agent.start_turn(
                body.conversation_id, body.message, regenerate=body.regenerate, edit_message_id=body.edit_message_id
            )
        except ConversationNotFound:
            raise HTTPException(404, "Conversation not found.")
        except ValueError as exc:
            raise HTTPException(422, str(exc))

        async def events() -> AsyncIterator[str]:
            rt.active.add(conversation["id"])
            try:
                async for event in rt.agent.run_turn(conversation, prefer=body.model):
                    yield _sse(event)
            finally:
                rt.active.discard(conversation["id"])

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @api.post("/transcribe")
    async def transcribe(request: Request) -> dict[str, str]:
        audio = await request.body()
        try:
            text = await rt.transcribe_audio(
                audio,
                request.headers.get("x-jarvis-filename", "recording.webm"),
                request.headers.get("content-type", "audio/webm"),
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        return {"text": text}

    @api.post("/approvals/{approval_id}")
    def resolve_approval(approval_id: str, body: ApprovalRequest) -> dict[str, bool]:
        if not rt.approvals.resolve(approval_id, body.approve, body.always):
            raise HTTPException(404, "That request is no longer waiting.")
        return {"ok": True}

    # ----- memory ----------------------------------------------------------

    @api.get("/memories")
    def list_memories(q: str = "", kind: str = "") -> dict[str, Any]:
        memories = rt.store.search_memories(q, 50) if q.strip() else rt.store.list_memories()
        if kind:
            memories = [memory for memory in memories if memory["kind"] == kind]
        return {"memories": memories, "total": rt.store.counts()["memories"], "seq": rt.change_seq}

    @api.get("/memories/export")
    def export_memories() -> dict[str, Any]:
        return rt.memory.export()

    @api.get("/memories/changes")
    def memory_changes(after: int = 0) -> dict[str, Any]:
        return {"changes": rt.memory_changes(after), "seq": rt.change_seq}

    @api.post("/memories")
    def create_memory(body: MemoryCreate) -> dict[str, Any]:
        try:
            memory, created = rt.memory.add(body.content, body.kind, source="user")
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        return {"memory": memory, "created": created}

    @api.patch("/memories/{memory_id}")
    def update_memory(memory_id: int, body: MemoryUpdate) -> dict[str, Any]:
        try:
            memory = rt.memory.replace(memory_id, content=body.content, kind=body.kind, pinned=body.pinned)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        if memory is None:
            raise HTTPException(404, "Memory not found.")
        return memory

    @api.delete("/memories/{memory_id}", status_code=204)
    def delete_memory(memory_id: int) -> Response:
        if rt.memory.forget(memory_id) is None:
            raise HTTPException(404, "Memory not found.")
        return Response(status_code=204)

    @api.delete("/memories")
    def delete_all_memories() -> dict[str, int]:
        return {"deleted": rt.store.delete_all_memories()}

    # ----- activity, tools, status -----------------------------------------

    @api.get("/reminders")
    def reminders() -> list[dict[str, Any]]:
        return rt.reminders.list()

    @api.delete("/reminders/{reminder_id}")
    def cancel_reminder(reminder_id: int) -> dict[str, bool]:
        if not rt.reminders.cancel(reminder_id):
            raise HTTPException(404, "Pending reminder not found.")
        return {"ok": True}

    @api.get("/notices")
    def notices(after: int = 0) -> dict[str, Any]:
        recent = rt.reminders.notices()
        return {"notices": [item for item in recent if item["seq"] > max(0, after)],
                "seq": recent[-1]["seq"] if recent else 0}

    @api.get("/activity")
    def activity(limit: int = 200) -> dict[str, Any]:
        return {"runs": rt.store.list_tool_runs(min(max(limit, 1), 500)), "pending": rt.approvals.pending()}

    @api.get("/tools")
    def tools() -> list[dict[str, Any]]:
        return tools_payload()

    @api.get("/status")
    def status() -> dict[str, Any]:
        prefs = rt.prefs.all()
        usage = {row["model"]: row for row in rt.store.usage_for_day()}
        models = [
            {
                "model": label,
                "resting_seconds": round(rt.router.resting_seconds(label)),
                "rate": rt.router.rate.get(label),
                "usage": usage.get(label),
            }
            for label in rt.router.labels
        ]
        db_size = rt.store.path.stat().st_size if rt.store.path.exists() else 0
        return {
            "version": __version__,
            "uptime_seconds": round(time.time() - rt.started),
            "models": models,
            "skipped": rt.router.skipped,
            "keys": rt.key_status(),
            "usage_today": list(usage.values()),
            "daily_request_limit": prefs["daily_request_limit"],
            "database": {"path": str(rt.store.path), "bytes": db_size, "search_index": rt.store.fts, **rt.store.counts()},
            "memory": {"enabled": prefs["memory_enabled"], "auto_learn": prefs["auto_learn"]},
            "apps": {"backend": rt.launcher.backend},
            "local_only": local_only,
            "workspace": str(rt.settings.workspace),
        }

    @api.post("/shutdown")
    def shutdown() -> dict[str, bool]:
        # Give the response time to leave, then stop the server the same way Ctrl+C would.
        threading.Timer(0.4, lambda: os.kill(os.getpid(), signal.SIGINT)).start()
        return {"ok": True}

    app.include_router(api)

    @app.get("/", include_in_schema=False)
    def index() -> HTMLResponse:
        html = (WEB_DIR / "index.html").read_text(encoding="utf-8").replace("{{JARVIS_TOKEN}}", rt.token)
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    return app
