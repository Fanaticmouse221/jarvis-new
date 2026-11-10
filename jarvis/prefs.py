"""User preferences that can be changed in the app. Stored in the database.

Every value is validated on the way in, because these arrive from the browser.
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

from jarvis.config import Settings, parse_model_list
from jarvis.storage import Store

# Personality dials. Each value maps to one line of the system prompt (persona.py).
PERSONA_OPTIONS: dict[str, tuple[str, ...]] = {
    "formality": ("butler", "balanced", "casual"),
    "wit": ("off", "subtle", "playful"),
    "detail": ("brief", "balanced", "thorough"),
}
PERSONA_DEFAULTS: dict[str, str] = {"formality": "balanced", "wit": "subtle", "detail": "balanced"}

POLICIES = {"allow", "ask", "off"}


def _text(value: Any, limit: int, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be text.")
    value = value.strip()
    if len(value) > limit:
        raise ValueError(f"{name} is too long (limit {limit} characters).")
    return value


def _flag(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be true or false.")
    return value


def _number(value: Any, low: float, high: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number.")
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low:g} and {high:g}.")
    return value


def clean_folder(raw: Any) -> str:
    """Validate a folder the user wants JARVIS to access; return its resolved path."""
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("Folder path is empty.")
    path = Path(os.path.expandvars(raw.strip().strip('"'))).expanduser()
    if not path.is_absolute():
        raise ValueError(f"'{raw}' is not a full path. Example: C:\\Users\\you\\Documents\\School")
    try:
        path = path.resolve()
    except OSError as exc:
        raise ValueError(f"Can't read '{raw}': {exc}") from exc
    if not path.is_dir():
        raise ValueError(f"'{raw}' is not an existing folder.")
    if path == Path(path.anchor) or path == Path.home().resolve():
        raise ValueError("That folder is too broad. Choose a specific folder, not a whole drive or your home folder.")
    return str(path)


class Prefs:
    def __init__(self, store: Store, settings: Settings):
        self._store = store
        self._defaults: dict[str, Any] = {
            "user_name": settings.user_name,
            "user_title": settings.user_title,
            "models": [spec.label for spec in settings.models],
            "reasoning_effort": settings.reasoning_effort,
            "custom_instructions": "",
            "persona": dict(PERSONA_DEFAULTS),
            "memory_enabled": True,
            "auto_learn": True,
            "ask_every_action": False,
            "tool_policy": {},
            "allowed_folders": [],
            "home_city": "",
            "max_steps": 8,
            "daily_request_limit": 0,
        }

    def all(self) -> dict[str, Any]:
        merged = copy.deepcopy(self._defaults)
        for key, value in self._store.get_settings().items():
            if key not in merged:
                continue
            if key == "persona" and isinstance(value, dict):
                merged["persona"].update({k: v for k, v in value.items() if k in PERSONA_DEFAULTS})
            else:
                merged[key] = value
        return merged

    def get(self, key: str) -> Any:
        return self.all()[key]

    def update(self, patch: dict[str, Any]) -> dict[str, Any]:
        """Validate and save a partial update. Raises ValueError with a readable message."""
        if not isinstance(patch, dict):
            raise ValueError("Settings update must be an object.")
        current = self.all()
        cleaned: dict[str, Any] = {}
        for key, value in patch.items():
            if key not in self._defaults:
                raise ValueError(f"Unknown setting '{key}'.")
            cleaned[key] = self._clean(key, value, current)
        for key, value in cleaned.items():
            self._store.set_setting(key, value)
        return self.all()

    def _clean(self, key: str, value: Any, current: dict[str, Any]) -> Any:
        if key == "user_name":
            return _text(value, 60, "Name")
        if key == "home_city":
            return _text(value, 100, "Home city")
        if key == "user_title":
            return _text(value, 30, "Form of address")
        if key == "custom_instructions":
            return _text(value, 1500, "Custom instructions")
        if key == "reasoning_effort":
            if value not in ("", "low", "medium", "high"):
                raise ValueError("Thinking effort must be low, medium or high.")
            return value
        if key in ("memory_enabled", "auto_learn", "ask_every_action"):
            return _flag(value, key)
        if key == "max_steps":
            return int(_number(value, 1, 15, "Step limit"))
        if key == "daily_request_limit":
            return int(_number(value, 0, 100000, "Daily request limit"))
        if key == "models":
            if not isinstance(value, list) or not value:
                raise ValueError("Choose at least one model.")
            if len(value) > 8:
                raise ValueError("At most 8 models.")
            labels: list[str] = []
            for item in value:
                (spec,) = parse_model_list(_text(item, 160, "Model"))
                if spec.label not in labels:
                    labels.append(spec.label)
            return labels
        if key == "tool_policy":
            if not isinstance(value, dict):
                raise ValueError("tool_policy must be an object.")
            merged = dict(current["tool_policy"])
            for name, policy in value.items():
                if policy is None:
                    merged.pop(name, None)
                elif policy in POLICIES:
                    merged[str(name)] = policy
                else:
                    raise ValueError(f"Permission for '{name}' must be allow, ask or off.")
            return merged
        if key == "allowed_folders":
            if not isinstance(value, list) or len(value) > 12:
                raise ValueError("allowed_folders must be a list of at most 12 folders.")
            folders: list[str] = []
            for item in value:
                folder = clean_folder(item)
                if folder not in folders:
                    folders.append(folder)
            return folders
        if key == "persona":
            if not isinstance(value, dict):
                raise ValueError("persona must be an object.")
            persona = dict(current["persona"])
            for name, item in value.items():
                options = PERSONA_OPTIONS.get(name)
                if options is None:
                    raise ValueError(f"Unknown personality setting '{name}'.")
                if item not in options:
                    raise ValueError(f"{name} must be one of: {', '.join(options)}.")
                persona[name] = item
            return persona
        raise ValueError(f"Unknown setting '{key}'.")
