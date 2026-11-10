"""Offline stand-in models for tests and for trying JARVIS without an API key.

None of these is an AI. They exist so the rest of the system (tools, memory,
approvals, the interface) can be exercised for real without a network.

  fake:agent      a small scripted "brain": recognises a few phrasings and calls
                  real tools for them. Also answers JARVIS's own memory-extraction
                  and summarising prompts with simple rules.
  fake:demo       slowly streams a formatting showcase
  fake:echo       replies with a short canned answer quoting the last message
  fake:script     replays a list of prepared replies (tests)
  fake:fail       always fails                (tests: fallback)
  fake:empty      returns nothing             (tests: fallback)
  fake:ratelimit  always answers "rate limited" (tests: cooldown)
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from typing import Any, AsyncIterator

from jarvis.llm.base import ChatMessage, LLMError, StreamEvent, ToolCall

DEMO_REPLY = """\
Demo mode, sir. No AI model is connected, so this is a canned reply, but the interface is fully operational.

## What I can render
- **Bold**, *italic* and `inline code`
- Maths, inline \\( e^{i\\pi} + 1 = 0 \\) and displayed:

$$ \\int_0^1 x^2 \\, dx = \\left[ \\frac{x^3}{3} \\right]_0^1 = \\frac{1}{3} $$

| System | Status |
|---|---|
| Interface | Online |
| Language model | Not connected |

```python
def greet(name: str) -> str:
    return f"Good evening, {name}."
```

> Add a free Groq key in Settings to bring the real model online.
"""

# Markers that identify JARVIS's internal prompts (see memory.py).
REFLECT_MARKER = "You maintain the long-term memory"
SUMMARY_MARKER = "You compress conversations"


def _call(tool: str, /, **arguments: Any) -> ToolCall:
    return ToolCall(id=f"call_{uuid.uuid4().hex[:10]}", name=tool, arguments=json.dumps(arguments))


def _extract_memories(user_text: str) -> dict[str, Any]:
    """Rule-based stand-in for the memory-extraction model."""
    text = user_text.strip()
    rules = [
        (r"\bmy name is ([A-Z][\w'-]+)", "personal", "Their name is {0}."),
        (r"\bcall me ([A-Z][\w'-]+)", "style", "Wants to be called {0}."),
        (r"\bi(?:'m| am) (?:studying|learning|revising) ([^.!?\n]+)", "project", "Is studying {0}."),
        (r"\bi(?:'m| am) (?:working on|building|making) ([^.!?\n]+)", "project", "Is working on {0}."),
        (r"\bi (?:prefer|like|love|enjoy) ([^.!?\n]+)", "preference", "Likes {0}."),
        (r"\bi (?:hate|dislike|can't stand) ([^.!?\n]+)", "preference", "Dislikes {0}."),
        (r"\bi live in ([^.!?\n]+)", "personal", "Lives in {0}."),
        (r"\b(?:from now on|in future),? ([^.!?\n]+)", "style", "{0}."),
    ]
    add = []
    for pattern, kind, template in rules:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = match.group(1).strip().rstrip(",")
            content = template.format(value[0].upper() + value[1:] if template.startswith("{0}") else value)
            add.append({"kind": kind, "content": content})
    return {"add": add[:3], "update": []}


def scripted_reply(messages: list[ChatMessage], tools: list[dict[str, Any]] | None) -> tuple[str, list[ToolCall]]:
    """The fake:agent brain. Returns (text, tool calls) for the current step."""
    system = messages[0].content if messages and messages[0].role == "system" else ""
    last = messages[-1] if messages else ChatMessage("user", "")

    if REFLECT_MARKER in system:
        user_part = last.content.split("User message:", 1)[-1].split("Assistant reply:", 1)[0]
        return json.dumps(_extract_memories(user_part)), []
    if SUMMARY_MARKER in system:
        return "Earlier, the user and JARVIS discussed: " + " ".join(last.content.split())[:240], []

    offered = {tool["function"]["name"] for tool in tools or []}

    if last.role == "tool":
        result = last.content.strip()
        if result.startswith("ERROR"):
            return f"That didn't work, I'm afraid. {result[6:].strip()}", []
        first_line = result.splitlines()[0] if result else "Done."
        return f"{first_line}", []

    text = last.content.strip()
    lower = text.lower()

    def use(tool: str, /, **arguments: Any) -> tuple[str, list[ToolCall]]:
        if tool not in offered:
            return f"I'd use my {tool} tool for that, but it is switched off.", []
        return "", [_call(tool, **arguments)]

    if "formatting demo" in lower:
        return DEMO_REPLY, []
    match = re.match(r"(?:please )?remember (?:that )?(.+)", text, re.IGNORECASE)
    if match:
        fact = match.group(1).strip().rstrip(".")
        kind = "style" if re.search(r"\b(call me|answers?|replies|reply)\b", fact, re.I) else "preference"
        return use("remember", content=fact[0].upper() + fact[1:] + ".", kind=kind)
    match = re.match(r"forget (?:memory )?#?(\d+)", lower)
    if match:
        return use("forget", id=int(match.group(1)))
    known = re.search(r"### What you know about the user\n(.+?)(?:\n\n|\Z)", system, re.S)
    if re.search(r"what do you (?:know|remember) about me|what have you learned", lower):
        if known and not known.group(1).startswith("Nothing yet"):
            return "Here is what I have on file:\n\n" + known.group(1).strip(), []
        return "Nothing on file yet. Tell me something about yourself and I'll keep it.", []
    match = re.match(r"what do you (?:know|remember) about (.+?)\??$", lower)
    if match:
        return use("recall", query=match.group(1))
    match = re.match(r"(?:what|when) did we (?:discuss|talk about|say about) (.+?)\??$", lower)
    if match:
        return use("search_conversations", query=match.group(1))
    match = re.match(r"(?:search (?:the )?web for|web search) (.+)", text, re.I)
    if match:
        return use("web_search", query=match.group(1))
    match = re.match(r"read page (https?://\S+)", text, re.I)
    if match:
        return use("read_page", url=match.group(1))
    match = re.fullmatch(r"(?:what(?:'s| is) the )?weather(?: in (.+?))?\??", text, re.I)
    if match:
        return use("get_weather", **({"place": match.group(1)} if match.group(1) else {}))
    match = re.match(r"calculate (.+)", text, re.I)
    if match:
        return use("calculate", expression=match.group(1))
    match = re.fullmatch(r"list files(?: in (.+))?", text, re.I)
    if match:
        return use("list_files", **({"folder": match.group(1)} if match.group(1) else {}))
    match = re.match(r"read file (.+)", text, re.I)
    if match:
        return use("read_file", path=match.group(1))
    match = re.match(r"(create|append|overwrite) file (.+?): (.*)", text, re.I | re.S)
    if match:
        return use("write_file", mode=match.group(1).lower(), path=match.group(2), content=match.group(3))
    match = re.match(r"open file (.+)", text, re.I)
    if match:
        return use("open_file", path=match.group(1))
    match = re.fullmatch(r"(?:pc )?(play_pause|next|previous|volume_up|volume_down|mute|lock)", lower)
    if match:
        return use("pc_control", action=match.group(1))
    match = re.fullmatch(r"set volume to (\d+)(?:%)?", lower)
    if match:
        return use("pc_control", action="set_volume", value=int(match.group(1)))
    match = re.match(r"remind me in (\d+(?:\.\d+)?) minutes? to (.+)", text, re.I | re.S)
    if match:
        return use("set_reminder", in_minutes=float(match.group(1)), text=match.group(2))
    if lower in ("list reminders", "show reminders", "my reminders"):
        return use("list_reminders")
    match = re.fullmatch(r"cancel reminder #?(\d+)", lower)
    if match:
        return use("cancel_reminder", id=int(match.group(1)))
    match = re.match(r"(?:add|create) (?:a )?to-?do:?\s+(.+)", text, re.I | re.S)
    if match:
        return use("add_todo", title=match.group(1).strip())
    if lower in ("list to-dos", "list todos", "show to-dos", "show todos", "my to-dos", "my todos"):
        return use("list_todos")
    match = re.fullmatch(r"(?:complete|finish|done with) to-?do #?(\d+)", lower)
    if match:
        return use("change_todo", id=int(match.group(1)), status="completed")
    match = re.fullmatch(r"reopen to-?do #?(\d+)", lower)
    if match:
        return use("change_todo", id=int(match.group(1)), status="pending")
    match = re.fullmatch(r"(?:delete|remove) to-?do #?(\d+)", lower)
    if match:
        return use("delete_todo", id=int(match.group(1)))
    match = re.fullmatch(r"(?:rename|edit) to-?do #?(\d+) to (.+)", text, re.I)
    if match:
        return use("edit_todo", id=int(match.group(1)), title=match.group(2).strip())
    match = re.match(r"(?:create|make) (?:a )?plan:?\s+(.+?)\s+with steps? (.+)", text, re.I | re.S)
    if match:
        steps = [step.strip() for step in re.split(r"\s*(?:;|, then)\s*", match.group(2)) if step.strip()]
        return use("create_plan", title=match.group(1).strip(), steps=steps)
    if lower in ("list plans", "show plans", "my plans"):
        return use("list_plans")
    match = re.fullmatch(r"(?:complete|finish) plan #?(\d+) step #?(\d+)", lower)
    if match:
        return use("change_plan_step", plan_id=int(match.group(1)), step=int(match.group(2)), status="completed")
    match = re.fullmatch(r"reopen plan #?(\d+) step #?(\d+)", lower)
    if match:
        return use("change_plan_step", plan_id=int(match.group(1)), step=int(match.group(2)), status="pending")
    match = re.fullmatch(r"(?:resume|continue) plan #?(\d+)", lower)
    if match:
        return use("resume_plan", plan_id=int(match.group(1)))
    match = re.fullmatch(r"(?:begin|start) plan #?(\d+)", lower)
    if match:
        return use("begin_plan_step", plan_id=int(match.group(1)))
    match = re.fullmatch(r"(?:cancel|stop) plan #?(\d+)", lower)
    if match:
        return use("change_plan_status", plan_id=int(match.group(1)), status="cancelled")
    match = re.fullmatch(r"reopen plan #?(\d+)", lower)
    if match:
        return use("change_plan_status", plan_id=int(match.group(1)), status="active")
    match = re.fullmatch(r"(?:please )?(?:close|quit|exit) (.+?)[.!]?$", text, re.I)
    if match:
        return use("close_app", name=match.group(1).strip())
    match = re.match(r"move file (.+?) to (.+)", text, re.I)
    if match:
        return use("move_file", source=match.group(1).strip(), destination=match.group(2).strip())
    match = re.match(r"(?:delete|remove) file (.+)", text, re.I)
    if match:
        return use("delete_file", path=match.group(1).strip())
    match = re.match(r"open (https?://\S+)", text, re.IGNORECASE)
    if match:
        return use("open_url", url=match.group(1))
    match = re.match(r"(?:please )?(?:open|launch|start) (.+?)[.!]?$", text, re.IGNORECASE)
    if match:
        return use("open_app", name=match.group(1).strip())
    if re.search(r"\b(battery|cpu|ram|disk space|system (?:status|info))\b", lower):
        return use("get_system_info")

    return (
        "I'm running on the demo brain, which only understands a few phrasings: "
        f"\"remember that…\", \"open …\", \"what do you know about …\". You said: {text}",
        [],
    )


class FakeProvider:
    def __init__(self, model: str = "echo", delay: float = 0.0, script: list[list[StreamEvent]] | None = None):
        self.model = model
        self.delay = delay
        self.script = script or []
        self.label = f"fake:{model}"
        self.calls: list[tuple[list[ChatMessage], list[dict[str, Any]] | None]] = []

    async def _words(self, text: str) -> AsyncIterator[StreamEvent]:
        for piece in re.findall(r"\S+\s*", text):
            if self.delay:
                await asyncio.sleep(self.delay)
            yield StreamEvent("text", text=piece)

    async def stream_chat(
        self, messages: list[ChatMessage], tools: list[dict[str, Any]] | None = None
    ) -> AsyncIterator[StreamEvent]:
        self.calls.append((list(messages), tools))
        if self.model == "fail":
            raise LLMError("fake:fail always fails.", status=503)
        if self.model == "ratelimit":
            raise LLMError("fake:ratelimit is rate limited.", status=429, retry_after=0.05)
        if self.model == "empty":
            return
        if self.model == "script":
            events = self.script.pop(0) if self.script else [StreamEvent("text", text="(script exhausted)")]
            for event in events:
                yield event
            return
        if self.model == "demo":
            for index in range(0, len(DEMO_REPLY), 6):
                await asyncio.sleep(self.delay or 0.02)
                yield StreamEvent("text", text=DEMO_REPLY[index : index + 6])
            return
        if self.model == "agent":
            text, calls = scripted_reply(messages, tools)
            async for event in self._words(text):
                yield event
            for call in calls:
                yield StreamEvent("tool_call", tool_call=call)
            yield StreamEvent("usage", data={"prompt_tokens": 0, "completion_tokens": 0})
            return
        last_user = next((m.content for m in reversed(messages) if m.role == "user"), "")
        async for event in self._words(f"Offline test mode. You said: **{last_user}**"):
            yield event

    async def list_models(self) -> list[str]:
        return ["agent", "demo", "echo"]
