"""The tool framework: how JARVIS acts, and what keeps those actions safe.

A tool is a named function with a JSON-schema for its arguments, a risk level
and a handler. The agent (agent.py) validates the model's arguments against the
schema, applies the user's permission for the tool, asks for approval when
needed, runs the handler with a timeout and records the outcome.

Risk levels
  read       looks something up; changes nothing
  act        a small, visible, reversible action (open an app, save a memory)
  sensitive  hard to undo (overwriting or deleting). Always asks first.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

RISK_READ, RISK_ACT, RISK_SENSITIVE = "read", "act", "sensitive"
GROUPS = {"memory": "Memory", "computer": "This computer", "web": "Web", "files": "Approved files", "utilities": "Utilities", "reminders": "Reminders"}


class ToolError(Exception):
    """A tool could not do what was asked. The message is shown to the model and the user."""


@dataclass
class ToolResult:
    ok: bool
    text: str  # what the model reads
    summary: str = ""  # one line for the interface and the action log
    data: dict[str, Any] | None = None  # structured extras for the interface
    untrusted: bool = False  # content came from outside (web page, file)

    def __post_init__(self) -> None:
        if not self.summary:
            self.summary = (self.text.strip().splitlines() or [""])[0][:200]


@dataclass
class ToolContext:
    """Everything a tool handler may use. Built fresh for each turn."""

    conversation_id: str | None
    run_id: str
    services: dict[str, Any] = field(default_factory=dict)  # memory, store, launcher...
    tainted: bool = False  # set once untrusted content has been read in this turn
    channel: str = "app"  # app or telegram; both use the same permissions and memory


Handler = Callable[[dict[str, Any], ToolContext], Awaitable[ToolResult]]


@dataclass
class Tool:
    name: str
    group: str
    label: str  # short human name, e.g. "Open an app"
    description: str  # for the model
    parameters: dict[str, Any]  # JSON schema (object)
    risk: str
    handler: Handler
    describe: Callable[[dict[str, Any]], str]  # one line describing a specific call
    timeout: float = 30.0
    untrusted_output: bool = False
    risk_for: Callable[[dict[str, Any], ToolContext], str] | None = None

    def effective_risk(self, args: dict[str, Any], ctx: ToolContext) -> str:
        """Assess a validated call, without weakening the tool's baseline risk."""
        levels = (RISK_READ, RISK_ACT, RISK_SENSITIVE)
        risk = self.risk_for(args, ctx) if self.risk_for else self.risk
        if self.risk not in levels or risk not in levels:
            raise ToolError("The tool returned an invalid risk level; the action was not run.")
        return levels[max(levels.index(self.risk), levels.index(risk))]

    def schema(self) -> dict[str, Any]:
        # preserveWhitespace is a local validation instruction, not a model schema keyword.
        parameters = {
            **self.parameters,
            "properties": {
                key: {name: value for name, value in spec.items() if name != "preserveWhitespace"}
                for key, spec in self.parameters.get("properties", {}).items()
            },
        }
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": parameters},
        }

    def default_policy(self) -> str:
        return "ask" if self.risk == RISK_SENSITIVE else "allow"


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, *tools: Tool) -> None:
        for tool in tools:
            self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def policy(self, tool: Tool, prefs: dict[str, Any]) -> str:
        """The user's permission for a tool: allow, ask or off."""
        if tool.group == "memory" and not prefs.get("memory_enabled", True):
            return "off"
        policy = prefs.get("tool_policy", {}).get(tool.name, tool.default_policy())
        if tool.risk == RISK_SENSITIVE and policy == "allow":
            return "ask"  # sensitive tools can be switched off, but never set to run unasked
        return policy

    def enabled(self, prefs: dict[str, Any]) -> list[Tool]:
        return [tool for tool in self._tools.values() if self.policy(tool, prefs) != "off"]


def obj(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    """Shorthand for an object schema."""
    return {"type": "object", "properties": properties, "required": required or []}


def validate_args(schema: dict[str, Any], args: Any) -> tuple[dict[str, Any], str | None]:
    """Check and tidy tool arguments against the (small) schema subset JARVIS uses.

    Returns (clean_args, error). Unknown arguments are dropped, since models
    sometimes add extras; wrong types are coerced when that is unambiguous.
    """
    if not isinstance(args, dict):
        return {}, "arguments must be a JSON object"
    properties = schema.get("properties", {})
    clean: dict[str, Any] = {}
    for key, spec in properties.items():
        value = args.get(key)
        if value is None or (value == "" and not spec.get("preserveWhitespace")):
            if key in schema.get("required", []):
                return {}, f"missing required argument '{key}'"
            continue
        kind = spec.get("type")
        if kind == "string":
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                value = str(value)
            if not isinstance(value, str):
                return {}, f"'{key}' must be text"
            if not spec.get("preserveWhitespace"):
                value = value.strip()
            if "maxLength" in spec and len(value) > spec["maxLength"]:
                return {}, f"'{key}' is too long (limit {spec['maxLength']} characters)"
            if "enum" in spec and value not in spec["enum"]:
                return {}, f"'{key}' must be one of: {', '.join(spec['enum'])}"
        elif kind == "integer":
            if isinstance(value, str) and value.strip().lstrip("#-").isdigit():
                value = int(value.strip().lstrip("#"))
            if isinstance(value, float) and value.is_integer():
                value = int(value)
            if isinstance(value, bool) or not isinstance(value, int):
                return {}, f"'{key}' must be a whole number"
            if "minimum" in spec and value < spec["minimum"]:
                return {}, f"'{key}' must be at least {spec['minimum']}"
            if "maximum" in spec and value > spec["maximum"]:
                return {}, f"'{key}' must be at most {spec['maximum']}"
        elif kind == "number":
            if isinstance(value, str):
                try:
                    value = float(value)
                except ValueError:
                    return {}, f"'{key}' must be a number"
            if isinstance(value, bool) or not isinstance(value, (int, float)) or (isinstance(value, float) and not math.isfinite(value)):
                return {}, f"'{key}' must be a finite number"
            if "minimum" in spec and value < spec["minimum"]:
                return {}, f"'{key}' must be at least {spec['minimum']}"
            if "maximum" in spec and value > spec["maximum"]:
                return {}, f"'{key}' must be at most {spec['maximum']}"
        elif kind == "boolean":
            if isinstance(value, str) and value.lower() in ("true", "false"):
                value = value.lower() == "true"
            if not isinstance(value, bool):
                return {}, f"'{key}' must be true or false"
        clean[key] = value
    return clean, None
