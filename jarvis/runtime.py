"""Wires JARVIS together: storage, preferences, models, memory, tools and the agent.

One Runtime exists per running server. It also owns the things that change
while JARVIS runs: the model router (rebuilt when keys or models change), the
feed of recent memory changes, and background learning tasks.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from collections import deque
from typing import Any, Coroutine

from jarvis.agent import Agent, ApprovalBroker
from jarvis.config import KEY_ENV, Settings, save_api_key, save_telegram_token
from jarvis.llm import ChatMessage, LLMError, ModelRouter
from jarvis.llm.openai_compat import OpenAICompatProvider
from jarvis.llm.router import GROQ_PREFERRED, base_url_for
from jarvis.memory import Learner, Memory
from jarvis.prefs import Prefs
from jarvis.storage import Store, utc_now
from jarvis.telegram import TelegramService
from jarvis.tools import build_registry
from jarvis.tools.system_tools import AppLauncher, default_launcher

log = logging.getLogger("jarvis.runtime")


class Runtime:
    def __init__(
        self,
        settings: Settings,
        *,
        store: Store | None = None,
        router: ModelRouter | None = None,
        launcher: AppLauncher | None = None,
    ):
        self.settings = settings
        self.store = store or Store(settings.db_path)
        self.prefs = Prefs(self.store, settings)
        self.started = time.time()

        self._changes: deque[dict[str, Any]] = deque(maxlen=100)
        self._seq = 0
        self.memory = Memory(self.store, self._memory_changed)
        self.registry = build_registry()
        self.approvals = ApprovalBroker()
        self.launcher = launcher or default_launcher()
        self.services: dict[str, Any] = {"memory": self.memory, "store": self.store, "launcher": self.launcher,
                                         "settings": settings, "prefs": self.prefs}

        self._fixed_router = router  # tests inject one
        self.router: ModelRouter = router or self._build_router()
        self.learner = Learner(self.memory, lambda: self.router)
        self._tasks: set[asyncio.Task[Any]] = set()
        self.agent = Agent(
            settings=settings,
            prefs=self.prefs,
            store=self.store,
            memory=self.memory,
            learner=self.learner,
            registry=self.registry,
            approvals=self.approvals,
            services=self.services,
            get_router=lambda: self.router,
            spawn=self.spawn,
        )
        self.active: set[str] = set()  # conversations with a reply in progress
        self.token = self._load_token()
        self.telegram = TelegramService(self, token=settings.telegram_bot_token, api_base=settings.telegram_api)
        self._background_services: list[Any] = [self.telegram]
        self._running = False

    # ----- plumbing -------------------------------------------------------

    async def start(self) -> None:
        """Start server-owned services once, on the server's event loop."""
        if self._running:
            return
        self._running = True
        try:
            for service in self._background_services:
                await service.start()
        except BaseException:
            await self.stop()
            raise

    async def stop(self) -> None:
        """Cancel services and learning before their event loop closes."""
        self._running = False
        for service in reversed(self._background_services):
            await service.stop()
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _load_token(self) -> str:
        """A secret the interface must present on every API call (see security.py)."""
        token = self.store.get_setting("api_token")
        if not token:
            token = secrets.token_urlsafe(24)
            self.store.set_setting("api_token", token)
        return token

    def _build_router(self) -> ModelRouter:
        prefs = self.prefs.all()
        return ModelRouter.from_settings(
            self.settings,
            prefs["models"],
            reasoning_effort=prefs["reasoning_effort"],
            store=self.store,
            daily_limit=prefs["daily_request_limit"],
        )

    def reload_router(self) -> None:
        if self._fixed_router is None:
            self.router = self._build_router()

    def spawn(self, coro: Coroutine[Any, Any, Any]) -> None:
        """Run background work (learning, summaries) without holding up the reply."""
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)

        def finished(done: asyncio.Task[Any]) -> None:
            self._tasks.discard(done)
            if not done.cancelled() and done.exception():
                log.error("Background task failed", exc_info=done.exception())

        task.add_done_callback(finished)

    async def wait_for_background(self) -> None:
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    def _memory_changed(self, action: str, memory: dict[str, Any]) -> None:
        self._seq += 1
        self._changes.append({"seq": self._seq, "at": utc_now(), "action": action, "memory": memory})

    def memory_changes(self, after: int = 0) -> list[dict[str, Any]]:
        return [change for change in self._changes if change["seq"] > after]

    @property
    def change_seq(self) -> int:
        return self._seq

    # ----- settings that need more than a database write -------------------

    def update_prefs(self, patch: dict[str, Any]) -> dict[str, Any]:
        prefs = self.prefs.update(patch)
        if {"models", "reasoning_effort", "daily_request_limit"} & set(patch):
            self.reload_router()
        return prefs

    def key_status(self) -> dict[str, dict[str, Any]]:
        status = {}
        for provider in KEY_ENV:
            key = self.settings.key_for(provider)
            status[provider] = {"set": bool(key), "hint": f"…{key[-4:]}" if len(key) >= 8 else ""}
        return status

    def _apply_settings(self, settings: Settings) -> None:
        self.settings = settings
        self.agent.settings = settings
        self.services["settings"] = settings
        self.reload_router()

    async def list_provider_models(self, provider: str, key: str | None = None) -> list[str]:
        base_url = base_url_for(provider, self.settings)
        if not base_url:
            raise ValueError(f"Model listing isn't available for '{provider}'.")
        client = OpenAICompatProvider(
            provider=provider, base_url=base_url, model="-", api_key=key or self.settings.key_for(provider) or None, timeout=20
        )
        return await client.list_models()

    async def set_key(self, provider: str, key: str) -> dict[str, Any]:
        """Check a key with the provider, save it to .env, and bring its models online."""
        if provider not in KEY_ENV:
            raise ValueError(f"Unknown provider '{provider}'.")
        key = key.strip()
        if len(key) < 8:
            raise ValueError("That doesn't look like a complete API key.")
        warning = ""
        available: list[str] = []
        if provider != "custom":
            try:
                available = await self.list_provider_models(provider, key)
            except LLMError as exc:
                if exc.status in (401, 403):
                    raise ValueError(f"{provider.title()} rejected that key. Copy it again and make sure nothing is cut off.") from exc
                warning = "Saved, but the key couldn't be verified just now (no connection to the provider)."
        self._apply_settings(save_api_key(self.settings, provider, key))

        if provider == "groq" and available:
            # First key: choose a model order from what this account can actually use.
            current = self.prefs.get("models")
            usable = [label for label in current if label.startswith("groq:") and label[5:] in available]
            customised = "models" in self.store.get_settings() and not all(label.startswith("fake:") for label in current)
            if not usable or not customised:
                chosen = [f"groq:{model}" for model in GROQ_PREFERRED if model in available][:3]
                if chosen:
                    self.update_prefs({"models": chosen})
        return {"ok": True, "warning": warning, "models": self.router.labels, "skipped": self.router.skipped}

    def remove_key(self, provider: str) -> None:
        self._apply_settings(save_api_key(self.settings, provider, None))

    async def set_telegram_token(self, token: str) -> dict[str, Any]:
        bot = await self.telegram.verify_token(token.strip())
        self._apply_settings(save_telegram_token(self.settings, token))
        await self.telegram.configure(self.settings.telegram_bot_token, bot=bot)
        return self.telegram.status()

    async def remove_telegram(self) -> dict[str, Any]:
        self._apply_settings(save_telegram_token(self.settings, None))
        await self.telegram.remove()
        return self.telegram.status()

    # ----- diagnostics ----------------------------------------------------

    async def check_models(self) -> list[dict[str, Any]]:
        """Send a tiny prompt to each configured model and report what works."""
        results: list[dict[str, Any]] = []
        messages = [
            ChatMessage("system", "You are a connectivity test. Reply with exactly: Systems online."),
            ChatMessage("user", "Status check."),
        ]
        for provider in self.router.providers:
            started = time.perf_counter()
            try:
                reply = "".join([event.text async for event in provider.stream_chat(messages) if event.kind == "text"])
                ok = bool(reply.strip())
                detail = reply.strip()[:80] if ok else "The model returned an empty reply."
            except LLMError as exc:
                ok, detail = False, str(exc)
            self.store.record_usage(provider.label, error=not ok)
            results.append(
                {"model": provider.label, "ok": ok, "detail": detail, "seconds": round(time.perf_counter() - started, 2)}
            )
        for reason in self.router.skipped:
            results.append({"model": reason.split(": ", 1)[0], "ok": False, "detail": reason, "seconds": 0})
        return results
