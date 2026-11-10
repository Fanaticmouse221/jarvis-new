"""Agent tools for durable multi-step plans."""

from typing import Any

from jarvis.tools.base import RISK_ACT, RISK_READ, Tool, ToolContext, ToolError, ToolResult, obj


async def create_plan(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    try:
        plan = ctx.services["store"].create_plan(
            args["title"], args["steps"], ctx.conversation_id
        )
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    return ToolResult(
        True,
        f"Created plan #{plan['id']}: {plan['title']} ({len(plan['steps'])} steps)",
        data={"plan": plan},
    )


async def list_plans(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    try:
        plans = ctx.services["store"].list_plans(args.get("status", "active"))
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    if not plans:
        return ToolResult(True, "There are no matching plans.", summary="No matching plans")
    lines = []
    for plan in plans:
        lines.append(f"Plan #{plan['id']} [{plan['status']}] {plan['title']}")
        for step in plan["steps"]:
            marker = "x" if step["status"] == "completed" else " "
            lines.append(f"  [{marker}] {step['position']}. {step['title']}")
    return ToolResult(True, "\n".join(lines)[:2800], summary=f"{len(plans)} plans")


TOOLS = [
    Tool(
        "create_plan",
        "tasks",
        "Create a plan",
        "Create a durable multi-step plan that survives restarts.",
        obj(
            {
                "title": {"type": "string", "maxLength": 500},
                "steps": {"type": "array", "items": {"type": "string", "maxLength": 500}, "minItems": 1, "maxItems": 50},
            },
            ["title", "steps"],
        ),
        RISK_ACT,
        create_plan,
        lambda a: f"Create plan: {a.get('title', '')[:70]}",
    ),
    Tool(
        "list_plans",
        "tasks",
        "List plans",
        "List active, completed or cancelled durable plans.",
        obj({"status": {"type": "string", "enum": ["active", "completed", "cancelled", "all"]}}),
        RISK_READ,
        list_plans,
        lambda a: f"List {a.get('status', 'active')} plans",
    ),
]
