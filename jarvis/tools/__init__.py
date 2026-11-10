"""JARVIS's tools. `build_registry()` returns everything currently implemented."""

from jarvis.tools import memory_tools, system_tools, file_tools, utility_tools, web_tools
from jarvis.tools.base import (
    GROUPS,
    RISK_ACT,
    RISK_READ,
    RISK_SENSITIVE,
    Tool,
    ToolContext,
    ToolError,
    ToolRegistry,
    ToolResult,
    validate_args,
)


def build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(*memory_tools.TOOLS, *system_tools.TOOLS, *web_tools.TOOLS, *file_tools.TOOLS, *utility_tools.TOOLS)
    return registry


__all__ = [
    "GROUPS",
    "RISK_ACT",
    "RISK_READ",
    "RISK_SENSITIVE",
    "Tool",
    "ToolContext",
    "ToolError",
    "ToolRegistry",
    "ToolResult",
    "build_registry",
    "validate_args",
]
