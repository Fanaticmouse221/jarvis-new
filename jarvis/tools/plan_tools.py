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
        if plan.get("next_step"):
            lines.append(f"  Next: {plan['next_step']['position']}. {plan['next_step']['title']}")
        for step in plan["steps"]:
            marker = "x" if step["status"] == "completed" else " "
            lines.append(f"  [{marker}] {step['position']}. {step['title']}")
    return ToolResult(True, "\n".join(lines)[:2800], summary=f"{len(plans)} plans")


async def resume_plan(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    plan = ctx.services["store"].get_plan(args["plan_id"])
    if plan is None:
        raise ToolError("That plan was not found. Use list_plans to check its number.")
    if plan["next_step"] is None:
        return ToolResult(True, f"Plan #{plan['id']} is complete: {plan['title']}", data={"plan": plan})
    step = plan["next_step"]
    return ToolResult(
        True,
        f"Next step for plan #{plan['id']} ({plan['title']}): {step['position']}. {step['title']}",
        data={"plan": plan},
    )


async def change_plan_status(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    try:
        plan = ctx.services["store"].update_plan_status(args["plan_id"], args["status"])
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    if plan is None:
        raise ToolError("That plan was not found. Use list_plans to check its number.")
    verb = "Cancelled" if args["status"] == "cancelled" else "Reopened"
    return ToolResult(True, f"{verb} plan #{plan['id']}: {plan['title']}", data={"plan": plan})


async def change_plan_step(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    plan = ctx.services["store"].update_plan_step(args["plan_id"], args["step"], args["status"])
    if plan is None:
        raise ToolError("That plan step was not found. Use list_plans to check the plan and step number.")
    verb = "Completed" if args["status"] == "completed" else "Reopened"
    return ToolResult(
        True,
        f"{verb} step {args['step']} of plan #{plan['id']}: {plan['title']}",
        data={"plan": plan},
    )


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
    Tool(
        "change_plan_step",
        "tasks",
        "Change a plan step",
        "Complete or reopen one step in a durable plan.",
        obj(
            {
                "plan_id": {"type": "integer", "minimum": 1},
                "step": {"type": "integer", "minimum": 1},
                "status": {"type": "string", "enum": ["completed", "pending"]},
            },
            ["plan_id", "step", "status"],
        ),
        RISK_ACT,
        change_plan_step,
        lambda a: f"{'Complete' if a.get('status') == 'completed' else 'Reopen'} plan #{a.get('plan_id', '?')} step {a.get('step', '?')}",
    ),
    Tool(
        "resume_plan",
        "tasks",
        "Resume a plan",
        "Show the next pending step in a durable plan.",
        obj({"plan_id": {"type": "integer", "minimum": 1}}, ["plan_id"]),
        RISK_READ,
        resume_plan,
        lambda a: f"Resume plan #{a.get('plan_id', '?')}",
    ),
    Tool(
        "change_plan_status",
        "tasks",
        "Cancel or reopen a plan",
        "Cancel an active plan or reopen a cancelled plan without losing its steps.",
        obj(
            {
                "plan_id": {"type": "integer", "minimum": 1},
                "status": {"type": "string", "enum": ["cancelled", "active"]},
            },
            ["plan_id", "status"],
        ),
        RISK_ACT,
        change_plan_status,
        lambda a: f"{'Cancel' if a.get('status') == 'cancelled' else 'Reopen'} plan #{a.get('plan_id', '?')}",
    ),
]
