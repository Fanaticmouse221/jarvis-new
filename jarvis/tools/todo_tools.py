"""Agent tools for durable to-dos."""

from typing import Any

from jarvis.tools.base import RISK_ACT, RISK_READ, RISK_SENSITIVE, Tool, ToolContext, ToolError, ToolResult, obj


async def add_todo(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    try:
        todo = ctx.services["store"].create_todo(
            args["title"], args.get("details", ""), ctx.conversation_id, args.get("due_at")
        )
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    return ToolResult(True, f"Added to-do #{todo['id']}: {todo['title']}", data={"todo": todo})


async def list_todos(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    try:
        todos = ctx.services["store"].list_todos(args.get("status", "pending"))
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    if not todos:
        return ToolResult(True, "There are no matching to-dos.", summary="No matching to-dos")
    lines = [
        f"#{item['id']} [{item['status']}] {item['title']}"
        + (f" — due {item['due_at']}" if item.get("due_at") else "")
        + (f" — {item['details']}" if item["details"] else "")
        for item in todos
    ]
    return ToolResult(True, "\n".join(lines)[:2800], summary=f"{len(todos)} to-dos")


async def change_todo(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    status = args["status"]
    todo = ctx.services["store"].update_todo_status(args["id"], status)
    if todo is None:
        raise ToolError("That to-do was not found. Use list_todos to check its number.")
    verb = "Completed" if status == "completed" else "Reopened"
    return ToolResult(True, f"{verb} to-do #{todo['id']}: {todo['title']}", data={"todo": todo})


async def delete_todo(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    todo = ctx.services["store"].delete_todo(args["id"])
    if todo is None:
        raise ToolError("That to-do was not found. Use list_todos to check its number.")
    return ToolResult(True, f"Deleted to-do #{todo['id']}: {todo['title']}", data={"todo": todo})


TOOLS = [
    Tool(
        "add_todo", "tasks", "Add a to-do",
        "Add a durable to-do with a short title, optional details and optional ISO due date.",
        obj({"title": {"type": "string", "maxLength": 500}, "details": {"type": "string", "maxLength": 2000},
             "due_at": {"type": "string", "maxLength": 40}}, ["title"]),
        RISK_ACT, add_todo, lambda a: f"Add to-do: {a.get('title', '')[:70]}",
    ),
    Tool(
        "list_todos", "tasks", "List to-dos",
        "List pending, completed or all to-dos.",
        obj({"status": {"type": "string", "enum": ["pending", "completed", "all"]}}),
        RISK_READ, list_todos, lambda a: f"List {a.get('status', 'pending')} to-dos",
    ),
    Tool(
        "change_todo", "tasks", "Change a to-do",
        "Complete or reopen a to-do by number.",
        obj({"id": {"type": "integer", "minimum": 1}, "status": {"type": "string", "enum": ["completed", "pending"]}}, ["id", "status"]),
        RISK_ACT, change_todo, lambda a: f"{'Complete' if a.get('status') == 'completed' else 'Reopen'} to-do #{a.get('id', '?')}",
    ),
    Tool(
        "delete_todo", "tasks", "Delete a to-do",
        "Permanently delete a to-do by number. This always requires approval.",
        obj({"id": {"type": "integer", "minimum": 1}}, ["id"]),
        RISK_SENSITIVE, delete_todo, lambda a: f"Delete to-do #{a.get('id', '?')}",
    ),
]
