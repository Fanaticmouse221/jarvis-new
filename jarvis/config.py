"""Configuration, loaded from environment variables and an optional `.env` file.

Everything JARVIS needs to know about its environment lives here, so the rest of
the code never reads `os.environ` directly. Secrets (API keys) only ever come
from the environment / `.env`, which git ignores.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class ModelSpec:
    """One entry in the model priority list, e.g. ``groq:openai/gpt-oss-120b``."""

    provider: str
    model: str

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}"


def parse_model_list(raw: str) -> list[ModelSpec]:
    """Parse ``"provider:model, provider:model"`` into ModelSpecs.

    Only the first colon separates provider from model, so model IDs that
    contain colons (e.g. OpenRouter's ``openai/gpt-oss-120b:free``) work.
    """
    specs: list[ModelSpec] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        provider, sep, model = item.partition(":")
        if not sep or not provider.strip() or not model.strip():
            raise ValueError(
                f"Invalid JARVIS_MODELS entry {item!r}: expected 'provider:model', "
                "for example 'groq:openai/gpt-oss-120b'."
            )
        specs.append(ModelSpec(provider.strip().lower(), model.strip()))
    return specs


def _int(value: str | None, default: int) -> int:
    try:
        return int(value) if value not in (None, "") else default
    except ValueError:
        return default


def _float(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def _bool(value: str | None, default: bool) -> bool:
    if value in (None, ""):
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


DEFAULT_MODELS = "groq:openai/gpt-oss-120b,groq:llama-3.1-8b-instant"


@dataclass(frozen=True)
class Settings:
    # Models in priority order; the first one that answers wins.
    models: list[ModelSpec] = field(default_factory=lambda: parse_model_list(DEFAULT_MODELS))
    # API keys by environment-variable name, e.g. {"GROQ_API_KEY": "..."}.
    api_keys: dict[str, str] = field(default_factory=dict)
    ollama_base_url: str = "http://localhost:11434/v1"
    custom_base_url: str = ""
    reasoning_effort: str = "low"
    max_output_tokens: int = 4096
    temperature: float | None = None
    request_timeout: float = 90.0

    user_name: str = ""
    user_title: str = "sir"

    host: str = "127.0.0.1"
    port: int = 8000
    open_browser: bool = True
    db_path: Path = Path("data/jarvis.db")

    max_history_messages: int = 30
    max_context_chars: int = 12000

    @classmethod
    def from_env(cls, env_file: Path | None = None) -> "Settings":
        """Build settings from the process environment plus `.env` (cwd by default).

        Real environment variables take priority over `.env` values.
        """
        load_dotenv(env_file or Path.cwd() / ".env", override=False)
        env = os.environ.get

        key_names = ("GROQ_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY", "JARVIS_CUSTOM_API_KEY")
        api_keys = {name: env(name, "").strip() for name in key_names if env(name, "").strip()}

        db_path = Path(env("JARVIS_DB_PATH", "data/jarvis.db"))
        if not db_path.is_absolute():
            db_path = Path.cwd() / db_path

        return cls(
            models=parse_model_list(env("JARVIS_MODELS", "") or DEFAULT_MODELS),
            api_keys=api_keys,
            ollama_base_url=env("OLLAMA_BASE_URL", "") or "http://localhost:11434/v1",
            custom_base_url=env("JARVIS_CUSTOM_BASE_URL", ""),
            reasoning_effort=env("JARVIS_REASONING_EFFORT", "low").strip().lower(),
            max_output_tokens=_int(env("JARVIS_MAX_OUTPUT_TOKENS"), 4096),
            temperature=_float(env("JARVIS_TEMPERATURE")),
            request_timeout=float(_int(env("JARVIS_REQUEST_TIMEOUT"), 90)),
            user_name=env("JARVIS_USER_NAME", "").strip(),
            user_title=env("JARVIS_USER_TITLE", "sir").strip(),
            host=env("JARVIS_HOST", "127.0.0.1").strip() or "127.0.0.1",
            port=_int(env("JARVIS_PORT"), 8000),
            open_browser=_bool(env("JARVIS_OPEN_BROWSER"), True),
            db_path=db_path,
            max_history_messages=_int(env("JARVIS_MAX_HISTORY_MESSAGES"), 30),
            max_context_chars=_int(env("JARVIS_MAX_CONTEXT_CHARS"), 12000),
        )
