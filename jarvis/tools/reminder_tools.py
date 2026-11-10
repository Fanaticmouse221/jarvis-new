"""Small tool schemas for the persistent reminder service."""

from typing import Any

from jarvis.tools.base import RISK_ACT, RISK_READ, Tool, ToolContext, ToolError, ToolResult, obj


async def set_reminder(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    try:
        reminder = ctx.services["reminders"].create(**args, conversation_id=ctx.conversation_id)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    return ToolResult(True, f"Reminder #{reminder['id']} set for {reminder['due_local']}: {reminder['text']}"
                      + (f" (repeats {reminder['repeat']})" if reminder['repeat'] != 'none' else ''), data={"reminder": reminder})


async def list_reminders(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    reminders = ctx.services["reminders"].list()
    text = "\n".join(f"#{r['id']} {r['due_local']} [{r['repeat']}]: {r['text']}" for r in reminders)
    return ToolResult(True, text[:2800] or "There are no pending reminders.", summary=f"{len(reminders)} pending reminders")


async def cancel_reminder(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    if not ctx.services["reminders"].cancel(args["id"]):
        raise ToolError("That pending reminder was not found. Use list_reminders to check its number.")
    return ToolResult(True, f"Cancelled reminder #{args['id']}.")


TOOLS = [
    Tool("set_reminder", "reminders", "Set a reminder", "Remind at local ISO date-time or in_minutes. PC must be on.",
         obj({"text": {"type": "string", "maxLength": 500}, "at": {"type": "string"},
              "in_minutes": {"type": "number"}, "repeat": {"type": "string", "enum": ["none", "daily", "weekdays", "weekly"]}}, ["text"]),
         RISK_ACT, set_reminder, lambda a: "Set reminder: " + a.get("text", "")[:70]),
    Tool("list_reminders", "reminders", "List reminders", "List pending reminders and their numbers.", obj({}),
         RISK_READ, list_reminders, lambda a: "List reminders"),
    Tool("cancel_reminder", "reminders", "Cancel a reminder", "Cancel a pending reminder by number.",
         obj({"id": {"type": "integer", "minimum": 1}}, ["id"]),
         RISK_ACT, cancel_reminder, lambda a: f"Cancel reminder #{a.get('id', '?')}"),
]
