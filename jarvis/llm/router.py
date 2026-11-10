"""Builds providers from settings and routes requests with fallback and rate-limit handling.

The model list is tried in order. If a model fails *before* it has produced any
output (rate limit, outage, bad key, empty reply), the next one is tried. Once a
model has started answering, a failure is reported rather than silently
switching, so a reply is never stitched together from two models.

Rate limits: a model that answers HTTP 429 is rested for the time the provider
asks for. If every model is resting and the wait is short, the router waits
once and tries again, telling the caller why.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from contextlib import aclosing
from dataclasses import dataclass
from typing import Any, AsyncIterator

from jarvis.config import KEY_ENV, ModelSpec, Settings, parse_model_list
from jarvis.llm.base import ChatMessage, LLMError, LLMProvider, ToolCall
from jarvis.llm.fake import FakeProvider
from jarvis.llm.openai_compat import OpenAICompatProvider
from jarvis.storage import Store

log = logging.getLogger("jarvis.llm")

MAX_WAIT_SECONDS = 30.0  # longest the router will pause for a rate limit before giving up
DEFAULT_COOLDOWN = 20.0

BASE_URLS: dict[str, str] = {
    "groq": "https://api.groq.com/openai/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "openrouter": "https://openrouter.ai/api/v1",
}
PROVIDERS = (*BASE_URLS, "ollama", "custom", "fake")

# When a Groq key is first added, the model order is built from this wish-list,
# keeping only models the account can actually see.
GROQ_PREFERRED = (
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "qwen/qwen3.8-27b",
    "llama-3.3-70b-versatile",
)


def supports_reasoning_effort(model: str) -> bool:
    """gpt-oss models accept `reasoning_effort` on Groq, OpenRouter and Ollama."""
    return "gpt-oss" in model.lower()


class NoModelsAvailable(LLMError):
    pass


class AllModelsFailed(LLMError):
    def __init__(self, errors: list[str]):
        super().__init__("No model could answer:\n- " + "\n- ".join(errors))
        self.errors = errors


@dataclass
class RouterEvent:
    kind: str  # "model" | "token" | "tool_call" | "usage" | "status"
    value: str = ""
    tool_call: ToolCall | None = None
    data: dict[str, Any] | None = None


def base_url_for(provider: str, settings: Settings) -> str:
    if provider == "ollama":
        return settings.ollama_base_url
    if provider == "custom":
        return settings.custom_base_url
    return settings.base_urls.get(provider) or BASE_URLS.get(provider, "")


def build_provider(spec: ModelSpec, settings: Settings, reasoning_effort: str | None = None) -> LLMProvider:
    """Create a provider for one model entry. Raises ValueError if it can't be configured."""
    if spec.provider == "fake":
        return FakeProvider(spec.model)
    if spec.provider not in PROVIDERS:
        raise ValueError(f"Unknown provider '{spec.provider}' in {spec.label}. Known: {', '.join(PROVIDERS)}.")

    base_url = base_url_for(spec.provider, settings)
    if not base_url:
        raise ValueError(f"{spec.label}: set JARVIS_CUSTOM_BASE_URL in .env.")

    api_key = None
    key_env = KEY_ENV.get(spec.provider)
    if key_env:
        api_key = settings.api_keys.get(key_env)
        if not api_key and spec.provider != "custom":
            raise ValueError(f"{spec.label}: no {spec.provider.title()} API key yet. Add one in Settings.")

    effort = settings.reasoning_effort if reasoning_effort is None else reasoning_effort
    extra: dict[str, Any] = {}
    if effort and supports_reasoning_effort(spec.model):
        extra["reasoning_effort"] = effort

    return OpenAICompatProvider(
        provider=spec.provider,
        base_url=base_url,
        model=spec.model,
        api_key=api_key,
        timeout=settings.request_timeout,
        max_tokens=settings.max_output_tokens or None,
        temperature=settings.temperature,
        extra_body=extra,
    )


class ModelRouter:
    def __init__(
        self,
        providers: list[LLMProvider],
        skipped: list[str] | None = None,
        store: Store | None = None,
        daily_limit: int = 0,
    ):
        self.providers = providers
        self.skipped = skipped or []  # human-readable reasons models were left out
        self.store = store
        self.daily_limit = daily_limit
        self.rate: dict[str, dict[str, Any]] = {}  # last rate-limit headers seen, per model
        self._resting: dict[str, float] = {}  # model label -> monotonic time it may be used again

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        labels: list[str] | None = None,
        *,
        reasoning_effort: str | None = None,
        store: Store | None = None,
        daily_limit: int = 0,
    ) -> "ModelRouter":
        specs = parse_model_list(",".join(labels)) if labels else settings.models
        providers: list[LLMProvider] = []
        skipped: list[str] = []
        for spec in specs:
            try:
                providers.append(build_provider(spec, settings, reasoning_effort))
            except ValueError as exc:
                skipped.append(str(exc))
                log.warning("Skipping model: %s", exc)
        return cls(providers, skipped, store, daily_limit)

    @property
    def labels(self) -> list[str]:
        return [provider.label for provider in self.providers]

    def resting_seconds(self, label: str) -> float:
        return max(0.0, self._resting.get(label, 0.0) - time.monotonic())

    def _record(self, label: str, usage: dict[str, Any] | None, *, error: bool = False, limited: bool = False) -> None:
        if self.store is None:
            return
        usage = usage or {}
        self.store.record_usage(
            label,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            error=error,
            rate_limited=limited,
        )

    def _ordered(self, prefer: str | None) -> list[LLMProvider]:
        if not prefer:
            return list(self.providers)
        first = [provider for provider in self.providers if provider.label == prefer]
        return first + [provider for provider in self.providers if provider.label != prefer]

    async def stream_chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        prefer: str | None = None,
    ) -> AsyncIterator[RouterEvent]:
        if not self.providers:
            reasons = " ".join(self.skipped) or "No models are selected."
            raise NoModelsAvailable(f"No AI model is ready. {reasons}")
        if self.daily_limit and self.store is not None and self.store.requests_today() >= self.daily_limit:
            raise LLMError(
                f"Today's request limit ({self.daily_limit}) has been reached. Raise or remove it in Settings."
            )

        for attempt in range(2):
            errors: list[str] = []
            waits: list[float] = []
            for provider in self._ordered(prefer):
                label = provider.label
                rest = self.resting_seconds(label)
                if rest > 0:
                    waits.append(rest)
                    errors.append(f"{label} is rate-limited for another {math.ceil(rest)} s.")
                    continue

                tries_left = 2  # one retry when the model garbles a tool call
                while tries_left:
                    tries_left -= 1
                    started = False
                    usage: dict[str, Any] | None = None
                    try:
                        # aclosing() closes the HTTP stream promptly if the user stops the reply.
                        async with aclosing(provider.stream_chat(messages, tools)) as stream:
                            async for event in stream:
                                if event.kind == "rate":
                                    self.rate[label] = {**(event.data or {}), "at": time.time()}
                                    continue
                                if event.kind == "usage":
                                    usage = event.data
                                    continue
                                if not started:
                                    started = True
                                    yield RouterEvent("model", label)
                                if event.kind == "text":
                                    yield RouterEvent("token", event.text)
                                elif event.kind == "tool_call":
                                    yield RouterEvent("tool_call", tool_call=event.tool_call)
                        if started:
                            self._record(label, usage)
                            if usage:
                                yield RouterEvent("usage", label, data=usage)
                            return
                        self._record(label, usage, error=True)
                        errors.append(f"{label} returned an empty reply.")
                        break
                    except LLMError as exc:
                        self._record(label, usage, error=True, limited=exc.status == 429)
                        if started or exc.status == 413:
                            raise  # mid-reply failure, or a request too large for any retry to fix
                        errors.append(str(exc))
                        if exc.status == 429:
                            delay = min(exc.retry_after or DEFAULT_COOLDOWN, 600.0)
                            self._resting[label] = time.monotonic() + delay
                            waits.append(delay)
                            break
                        if exc.code == "tool_use_failed" and tries_left:
                            errors.pop()
                            continue
                        break
                log.warning("Model %s unavailable: %s", label, errors[-1] if errors else "")

            shortest = min(waits) if waits else None
            if attempt == 0 and shortest is not None and shortest <= MAX_WAIT_SECONDS:
                yield RouterEvent("status", f"Rate limit reached. Resuming in {math.ceil(shortest)} s.")
                await asyncio.sleep(shortest + 0.25)
                continue
            raise AllModelsFailed(errors)
