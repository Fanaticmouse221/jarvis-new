"""Builds providers from settings and routes requests with automatic fallback.

The model list is tried in order. If a model fails *before* it has produced any
text (rate limit, outage, bad key, empty reply), the next one is tried. Once a
model has started answering, a failure is reported rather than silently
switching, so a reply is never stitched together from two models.
"""

from __future__ import annotations

import logging
from contextlib import aclosing
from dataclasses import dataclass
from typing import AsyncIterator

from jarvis.config import ModelSpec, Settings
from jarvis.llm.base import ChatMessage, LLMError, LLMProvider
from jarvis.llm.fake import FakeProvider
from jarvis.llm.openai_compat import OpenAICompatProvider

log = logging.getLogger("jarvis.llm")


@dataclass(frozen=True)
class ProviderPreset:
    base_url: str
    key_env: str | None  # environment variable holding the API key; None = no key needed


PRESETS: dict[str, ProviderPreset] = {
    "groq": ProviderPreset("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "gemini": ProviderPreset("https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY"),
    "openrouter": ProviderPreset("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "ollama": ProviderPreset("", None),  # base URL comes from OLLAMA_BASE_URL
    "custom": ProviderPreset("", "JARVIS_CUSTOM_API_KEY"),  # base URL from JARVIS_CUSTOM_BASE_URL
}


def supports_reasoning_effort(model: str) -> bool:
    """gpt-oss models accept `reasoning_effort` on Groq, OpenRouter and Ollama."""
    return "gpt-oss" in model.lower()


class NoModelsAvailable(LLMError):
    pass


class AllModelsFailed(LLMError):
    def __init__(self, errors: list[str]):
        super().__init__("All configured models failed:\n- " + "\n- ".join(errors))
        self.errors = errors


@dataclass
class RouterEvent:
    kind: str  # "model" (which model is answering) | "token" (a chunk of text)
    value: str


def build_provider(spec: ModelSpec, settings: Settings) -> LLMProvider:
    """Create a provider for one model entry. Raises ValueError if it can't be configured."""
    if spec.provider == "fake":
        return FakeProvider(spec.model)

    preset = PRESETS.get(spec.provider)
    if preset is None:
        known = ", ".join([*PRESETS, "fake"])
        raise ValueError(f"Unknown provider '{spec.provider}' in {spec.label}. Known providers: {known}.")

    base_url = preset.base_url
    if spec.provider == "ollama":
        base_url = settings.ollama_base_url
    elif spec.provider == "custom":
        base_url = settings.custom_base_url
        if not base_url:
            raise ValueError(f"{spec.label}: set JARVIS_CUSTOM_BASE_URL in .env.")

    api_key = None
    if preset.key_env:
        api_key = settings.api_keys.get(preset.key_env)
        if not api_key and spec.provider != "custom":
            raise ValueError(f"{spec.label}: {preset.key_env} is not set in .env.")

    extra: dict[str, str] = {}
    if settings.reasoning_effort and supports_reasoning_effort(spec.model):
        extra["reasoning_effort"] = settings.reasoning_effort

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
    def __init__(self, providers: list[LLMProvider], skipped: list[str] | None = None):
        self.providers = providers
        self.skipped = skipped or []  # human-readable reasons models were left out

    @classmethod
    def from_settings(cls, settings: Settings) -> "ModelRouter":
        providers: list[LLMProvider] = []
        skipped: list[str] = []
        for spec in settings.models:
            try:
                providers.append(build_provider(spec, settings))
            except ValueError as exc:
                skipped.append(str(exc))
                log.warning("Skipping model: %s", exc)
        return cls(providers, skipped)

    @property
    def labels(self) -> list[str]:
        return [p.label for p in self.providers]

    async def stream_chat(self, messages: list[ChatMessage]) -> AsyncIterator[RouterEvent]:
        if not self.providers:
            reasons = "; ".join(self.skipped) or "JARVIS_MODELS is empty."
            raise NoModelsAvailable(
                f"No AI model is configured. {reasons} See README > Configuration."
            )

        errors: list[str] = []
        for provider in self.providers:
            started = False
            try:
                # aclosing() guarantees the HTTP stream is closed promptly if the
                # user stops the reply mid-way.
                async with aclosing(provider.stream_chat(messages)) as stream:
                    async for chunk in stream:
                        if not started:
                            started = True
                            yield RouterEvent("model", provider.label)
                        yield RouterEvent("token", chunk)
                if started:
                    return
                errors.append(f"{provider.label} returned an empty reply.")
            except LLMError as exc:
                if started:
                    raise
                errors.append(str(exc))
            log.warning("Model %s failed; trying the next one. %s", provider.label, errors[-1])
        raise AllModelsFailed(errors)
