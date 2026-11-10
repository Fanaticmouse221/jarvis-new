"""Static configuration, loaded from environment variables and an optional `.env` file.

Two layers of configuration exist:

* `Settings` (this file): things fixed for the life of the process, such as the
  port, the database path and API keys. They come from the environment / `.env`.
* `Prefs` (prefs.py): things the user changes in the app, such as the model
  order, permissions and voice. They live in the database.

Secrets (API keys) only ever live in `.env`, which git ignores.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

from dotenv import load_dotenv, set_key, unset_key


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
                f"Invalid model entry {item!r}: expected 'provider:model', "
                "for example 'groq:openai/gpt-oss-120b'."
            )
        specs.append(ModelSpec(provider.strip().lower(), model.strip()))
    return specs


# Environment variable that holds each provider's API key.
KEY_ENV: dict[str, str] = {
    "groq": "GROQ_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "custom": "JARVIS_CUSTOM_API_KEY",
}

# Groq rate limits apply per model, so a second model on the same key is extra capacity.
DEFAULT_MODELS = "groq:openai/gpt-oss-120b,groq:openai/gpt-oss-20b"


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


def default_workspace() -> Path:
    """The folder JARVIS may read and write by default: Documents/JARVIS."""
    documents = Path.home() / "Documents"
    return (documents if documents.is_dir() else Path.home()) / "JARVIS"


@dataclass(frozen=True)
class Settings:
    # Default model order; the user can override it in the app (stored as a pref).
    models: list[ModelSpec] = field(default_factory=lambda: parse_model_list(DEFAULT_MODELS))
    # API keys by environment-variable name, e.g. {"GROQ_API_KEY": "..."}.
    api_keys: dict[str, str] = field(default_factory=dict)
    ollama_base_url: str = "http://localhost:11434/v1"
    custom_base_url: str = ""
    base_urls: dict[str, str] = field(default_factory=dict)  # optional per-provider overrides
    reasoning_effort: str = "low"
    # Groq's free tier counts prompt + this reservation against 8,000 tokens/minute.
    max_output_tokens: int = 2048
    temperature: float | None = None
    request_timeout: float = 90.0

    user_name: str = ""
    user_title: str = "sir"

    host: str = "127.0.0.1"
    port: int = 8000
    open_browser: bool = True
    window: str = "app"  # app (own window via Edge) | browser | none
    db_path: Path = Path("data/jarvis.db")
    env_path: Path = Path(".env")
    workspace: Path = field(default_factory=default_workspace)
    telegram_bot_token: str = field(default="", repr=False)
    telegram_api: str = "https://api.telegram.org"
    transcription_model: str = "whisper-large-v3-turbo"

    max_history_messages: int = 24
    max_context_chars: int = 6000

    @classmethod
    def from_env(cls, env_file: Path | None = None) -> "Settings":
        """Build settings from the process environment plus `.env` (cwd by default).

        Real environment variables take priority over `.env` values.
        """
        env_path = env_file or Path.cwd() / ".env"
        load_dotenv(env_path, override=False)
        env = os.environ.get

        api_keys = {name: env(name, "").strip() for name in KEY_ENV.values() if env(name, "").strip()}

        db_path = Path(env("JARVIS_DB_PATH", "data/jarvis.db"))
        if not db_path.is_absolute():
            db_path = Path.cwd() / db_path
        workspace = Path(env("JARVIS_WORKSPACE", "")).expanduser() if env("JARVIS_WORKSPACE") else default_workspace()

        return cls(
            models=parse_model_list(env("JARVIS_MODELS", "") or DEFAULT_MODELS),
            api_keys=api_keys,
            ollama_base_url=env("OLLAMA_BASE_URL", "") or "http://localhost:11434/v1",
            custom_base_url=env("JARVIS_CUSTOM_BASE_URL", ""),
            base_urls={
                provider: env(f"JARVIS_{provider.upper()}_BASE_URL", "").strip()
                for provider in ("groq", "gemini", "openrouter")
                if env(f"JARVIS_{provider.upper()}_BASE_URL", "").strip()
            },
            reasoning_effort=env("JARVIS_REASONING_EFFORT", "low").strip().lower(),
            max_output_tokens=_int(env("JARVIS_MAX_OUTPUT_TOKENS"), 2048),
            temperature=_float(env("JARVIS_TEMPERATURE")),
            request_timeout=float(_int(env("JARVIS_REQUEST_TIMEOUT"), 90)),
            user_name=env("JARVIS_USER_NAME", "").strip(),
            user_title=env("JARVIS_USER_TITLE", "sir").strip(),
            host=env("JARVIS_HOST", "127.0.0.1").strip() or "127.0.0.1",
            port=_int(env("JARVIS_PORT"), 8000),
            open_browser=_bool(env("JARVIS_OPEN_BROWSER"), True),
            window=(env("JARVIS_WINDOW", "app").strip().lower() or "app"),
            db_path=db_path,
            env_path=env_path,
            workspace=workspace,
            telegram_bot_token=env("TELEGRAM_BOT_TOKEN", "").strip(),
            telegram_api=env("JARVIS_TELEGRAM_API", "https://api.telegram.org").rstrip("/"),
            transcription_model=env("JARVIS_TRANSCRIPTION_MODEL", "whisper-large-v3-turbo").strip() or "whisper-large-v3-turbo",
            max_history_messages=_int(env("JARVIS_MAX_HISTORY_MESSAGES"), 24),
            max_context_chars=_int(env("JARVIS_MAX_CONTEXT_CHARS"), 6000),
        )

    def key_for(self, provider: str) -> str:
        return self.api_keys.get(KEY_ENV.get(provider, ""), "")


def save_api_key(settings: Settings, provider: str, key: str | None) -> Settings:
    """Write (or remove) a provider's API key in `.env` and return updated settings.

    The key is written to disk and to this process's environment, and nowhere else.
    """
    name = KEY_ENV.get(provider)
    if name is None:
        raise ValueError(f"Unknown provider '{provider}'.")
    key = (key or "").strip()
    if any(ch.isspace() for ch in key):
        raise ValueError("An API key can't contain spaces or line breaks.")
    env_path = settings.env_path
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.touch(exist_ok=True)
    keys = dict(settings.api_keys)
    if key:
        set_key(str(env_path), name, key, quote_mode="never")
        os.environ[name] = key
        keys[name] = key
    else:
        unset_key(str(env_path), name)
        os.environ.pop(name, None)
        keys.pop(name, None)
    return replace(settings, api_keys=keys)


def save_telegram_token(settings: Settings, token: str | None) -> Settings:
    """Keep the bot credential in .env, never in the database or API responses."""
    token = (token or "").strip()
    if token and not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]{20,}", token):
        raise ValueError("That doesn't look like a complete BotFather token.")
    settings.env_path.parent.mkdir(parents=True, exist_ok=True)
    settings.env_path.touch(exist_ok=True)
    if token:
        set_key(str(settings.env_path), "TELEGRAM_BOT_TOKEN", token, quote_mode="never")
        os.environ["TELEGRAM_BOT_TOKEN"] = token
    else:
        unset_key(str(settings.env_path), "TELEGRAM_BOT_TOKEN")
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)
    return replace(settings, telegram_bot_token=token)
