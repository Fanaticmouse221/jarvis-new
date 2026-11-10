"""Tools that let JARVIS use its long-term memory and past conversations."""

from __future__ import annotations

from typing import Any

from jarvis.memory import Memory
from jarvis.storage import MEMORY_KINDS, Store
from jarvis.tools.base import RISK_ACT, RISK_READ, Tool, ToolContext, ToolError, ToolResult, obj


def _short(text: str, limit: int = 70) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


async def remember(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    memory: Memory = ctx.services["memory"]
    replaces = args.get("replaces_id")
    try:
        if replaces is not None:
            updated = memory.replace(replaces, content=args["content"], kind=args.get("kind"))
            if updated is None:
                raise ToolError(f"There is no memory #{replaces}. Use recall to find the right number.")
            return ToolResult(True, f"Updated memory #{updated['id']}: {updated['content']}", data={"memory": updated, "action": "updated"})
        saved, created = memory.add(args["content"], args.get("kind", "note"), "told", ctx.conversation_id)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    if not created:
        return ToolResult(True, f"Already known (memory #{saved['id']}): {saved['content']}", data={"memory": saved, "action": "known"})
    return ToolResult(True, f"Saved to memory (#{saved['id']}): {saved['content']}", data={"memory": saved, "action": "saved"})


async def recall(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    memory: Memory = ctx.services["memory"]
    query = args.get("query", "")
    hits = memory.recall(query)
    if not hits:
        return ToolResult(True, "Nothing in memory matches that.", summary="No matching memories")
    lines = [f"#{hit['id']} ({hit['kind']}) {hit['content']}" for hit in hits]
    return ToolResult(True, "\n".join(lines), summary=f"Found {len(hits)} memor{'y' if len(hits) == 1 else 'ies'}")


async def forget(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    memory: Memory = ctx.services["memory"]
    removed = memory.forget(args["id"])
    if removed is None:
        raise ToolError(f"There is no memory #{args['id']}. Use recall to find the right number.")
    return ToolResult(True, f"Forgotten: {removed['content']}", data={"memory": removed, "action": "forgotten"})


async def search_conversations(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    store: Store = ctx.services["store"]
    hits = store.search_messages(args["query"], limit=6, exclude_conversation=ctx.conversation_id)
    if not hits:
        return ToolResult(True, "No earlier conversation mentions that.", summary="No matching conversations")
    lines = [
        f"[{hit['created_at'][:10]}] \"{hit['title']}\" ({'user' if hit['role'] == 'user' else 'JARVIS'}): {' '.join(hit['snippet'].split())}"
        for hit in hits
    ]
    return ToolResult(True, "\n".join(lines), summary=f"Found {len(hits)} passage{'' if len(hits) == 1 else 's'} in past conversations")


TOOLS = [
    Tool(
        name="remember",
        group="memory",
        label="Save a memory",
        description=(
            "Save one lasting fact about the user to long-term memory: a preference, personal detail, project, "
            "or (kind 'style') how they want you to behave. Third person, one fact per call. "
            "To correct an existing memory, pass its number as replaces_id."
        ),
        parameters=obj(
            {
                "content": {"type": "string", "description": "The fact, e.g. 'Prefers worked solutions shown step by step.'", "maxLength": 400},
                "kind": {"type": "string", "enum": list(MEMORY_KINDS)},
                "replaces_id": {"type": "integer", "description": "Number of the memory this replaces.", "minimum": 1},
            },
            ["content", "kind"],
        ),
        risk=RISK_ACT,
        handler=remember,
        describe=lambda a: f"Remember: {_short(str(a.get('content', '')))}",
        timeout=10,
    ),
    Tool(
        name="recall",
        group="memory",
        label="Search memory",
        description="Search long-term memory for facts about the user that aren't already shown to you.",
        parameters=obj({"query": {"type": "string", "description": "Keywords to look for.", "maxLength": 200}}, ["query"]),
        risk=RISK_READ,
        handler=recall,
        describe=lambda a: f"Search memory for “{_short(str(a.get('query', '')), 50)}”",
        timeout=10,
    ),
    Tool(
        name="forget",
        group="memory",
        label="Forget a memory",
        description="Delete one memory by its number, when the user asks you to forget it or it is no longer true.",
        parameters=obj({"id": {"type": "integer", "description": "The memory's number.", "minimum": 1}}, ["id"]),
        risk=RISK_ACT,
        handler=forget,
        describe=lambda a: f"Forget memory #{a.get('id', '?')}",
        timeout=10,
    ),
    Tool(
        name="search_conversations",
        group="memory",
        label="Search past conversations",
        description="Search earlier conversations with the user for what was said about a topic.",
        parameters=obj({"query": {"type": "string", "description": "Keywords to look for.", "maxLength": 200}}, ["query"]),
        risk=RISK_READ,
        handler=search_conversations,
        describe=lambda a: f"Search past conversations for “{_short(str(a.get('query', '')), 50)}”",
        timeout=10,
    ),
]
