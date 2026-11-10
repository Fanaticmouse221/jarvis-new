"""Bounded arithmetic and small, explicit Windows controls."""

from __future__ import annotations

import ast
import asyncio
import ctypes
import math
import operator
import sys
from typing import Any

from jarvis.tools.base import RISK_ACT, RISK_READ, Tool, ToolContext, ToolError, ToolResult, obj

_BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod}
_FUNCTIONS = {name: getattr(math, name) for name in
              ("sqrt", "sin", "cos", "tan", "asin", "acos", "atan", "log", "log10", "exp", "ceil", "floor", "degrees", "radians")}
_FUNCTIONS.update(abs=abs, round=round)


def evaluate(expression: str) -> int | float:
    """Interpret a small AST, bounding every intermediate value and exponent."""
    if not isinstance(expression, str) or len(expression) > 300:
        raise ToolError("Use an expression of at most 300 characters.")
    try:
        tree = ast.parse(expression, mode="eval")
        if sum(1 for _ in ast.walk(tree)) > 100:
            raise ValueError("Expression has too many steps.")

        def visit(node: ast.AST) -> int | float:
            if isinstance(node, ast.Constant) and type(node.value) in (int, float):
                value = node.value
            elif isinstance(node, ast.Name) and node.id in ("pi", "e"):
                value = getattr(math, node.id)
            elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                value = visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
            elif isinstance(node, ast.BinOp):
                left, right = visit(node.left), visit(node.right)
                if isinstance(node.op, ast.Pow):
                    if abs(right) > 1000 or (abs(left) > 1 and right > 0 and right * math.log10(abs(left)) > 100):
                        raise ValueError("Power is too large.")
                    value = left ** right
                elif type(node.op) in _BINARY:
                    value = _BINARY[type(node.op)](left, right)
                else:
                    raise ValueError("That operator is not supported.")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCTIONS:
                if node.keywords or not 1 <= len(node.args) <= 2:
                    raise ValueError("Use one or two positional function arguments.")
                values = [visit(arg) for arg in node.args]
                if node.func.id == "round" and len(values) == 2:
                    if type(values[1]) is not int or abs(values[1]) > 100:
                        raise ValueError("Rounding digits must be a whole number between -100 and 100.")
                value = _FUNCTIONS[node.func.id](*values)
            else:
                raise ValueError("Only numbers, arithmetic, pi, e and common maths functions are supported.")
            if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 1e100:
                raise ValueError("Result is too large or is not a finite real number.")
            return value

        return visit(tree.body)
    except (SyntaxError, ValueError, TypeError, OverflowError, ZeroDivisionError, RecursionError) as exc:
        raise ToolError(f"Couldn't calculate that: {exc}") from exc


async def calculate(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    result = evaluate(args["expression"])
    return ToolResult(True, str(result), summary=f"Calculated {args['expression']}", data={"result": result})


class WindowsPCController:
    """No shell commands; only this fixed set of media keys and workstation lock."""

    KEYS = {"play_pause": 0xB3, "next": 0xB0, "previous": 0xB1,
            "volume_up": 0xAF, "volume_down": 0xAE, "mute": 0xAD}

    def perform(self, action: str, value: int | None = None) -> None:
        if sys.platform != "win32":
            raise ToolError("PC controls are only available on Windows.")
        user32 = ctypes.windll.user32

        def press(key: int) -> None:
            user32.keybd_event(key, 0, 0, 0)
            user32.keybd_event(key, 0, 2, 0)

        if action == "lock":
            if not user32.LockWorkStation():
                raise ToolError("Windows did not accept the request to lock the screen.")
        elif action == "set_volume":
            if type(value) is not int or not 0 <= value <= 100:
                raise ToolError("Volume must be a whole number from 0 to 100.")
            for _ in range(50):
                press(self.KEYS["volume_down"])
            for _ in range(round(value / 2)):
                press(self.KEYS["volume_up"])
        elif action in self.KEYS:
            press(self.KEYS[action])
        else:
            raise ToolError("That PC control is not supported.")


async def pc_control(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    action, value = args["action"], args.get("value")
    if action == "set_volume" and (type(value) is not int or not 0 <= value <= 100):
        raise ToolError("For set_volume, provide value from 0 to 100.")
    controller = ctx.services.get("pc_controller") or WindowsPCController()
    await asyncio.to_thread(controller.perform, action, value)
    detail = f"Sent {action.replace('_', ' ')} to Windows."
    if action == "set_volume":
        detail += f" Requested approximately {value}% volume; I cannot read the level back."
    else:
        detail += " The resulting state cannot be read back."
    return ToolResult(True, detail)


TOOLS = [
    Tool("calculate", "utilities", "Calculate", "Arithmetic and maths functions; angles in radians.",
         obj({"expression": {"type": "string", "maxLength": 300}}, ["expression"]),
         RISK_READ, calculate, lambda a: f"Calculate {a.get('expression', '')}"),
    Tool("pc_control", "computer", "Control the PC", "Send a Windows media, volume or lock command.",
         obj({"action": {"type": "string", "enum": [*WindowsPCController.KEYS, "set_volume", "lock"]},
              "value": {"type": "integer", "minimum": 0, "maximum": 100}}, ["action"]),
         RISK_ACT, pc_control, lambda a: f"PC: {a.get('action', '').replace('_', ' ')}"),
]
