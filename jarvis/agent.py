"""The agent: turns a user message into a reply, using tools along the way.

One turn works like this:

1. Build the context: personality, what JARVIS knows about the user, a summary
   of anything that has scrolled out of view, and recent history.
2. Ask the model. It either answers, or asks to use tools.
3. For each tool request: check arguments, check the user's permission, ask for
   approval if needed, run it for real, record the outcome, and hand the result
   back to the model. Repeat from step 2 until it answers or the step limit hits.
4. Save the reply with its steps, then learn from the exchange in the background.

Every event is streamed to the interface as it happens, so the user can see
what JARVIS is doing and stop it at any point.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from contextlib import aclosing
from typing import Any, AsyncIterator, Callable, Coroutine

from jarvis.config import Settings
from jarvis.llm import ChatMessage, LLMError, ModelRouter, RouterEvent, ToolCall
from jarvis.memory import SUMMARISE_AFTER, Learner, Memory, MemoryContext
from jarvis.persona import build_system_prompt
from jarvis.prefs import Prefs
from jarvis.storage import Store
from jarvis.tools import RISK_READ, RISK_SENSITIVE, Tool, ToolContext, ToolError, ToolRegistry, ToolResult, validate_args

log = logging.getLogger("jarvis.agent")

MAX_MESSAGE_CHARS = 20_000
TITLE_CHARS = 60
MAX_TOOL_RESULT_CHARS = 3000  # what the model sees of one tool result
REPLAY_RESULT_CHARS = 300  # what later turns see of an earlier tool result
REPLAY_TURNS = 2  # how many earlier tool-using replies are replayed in full
APPROVAL_TIMEOUT = 300.0

STEP_LIMIT_NOTE = (
    "(System note: the step limit for this task has been reached. Don't call any more tools. "
    "Tell the user what was completed and what remains.)"
)


class ConversationNotFound(Exception):
    pass


def make_title(text: str) -> str:
    """A conversation title from the first message: its first line, trimmed."""
    first_line = " ".join(text.strip().splitlines()[0].split()) if text.strip() else ""
    if len(first_line) <= TITLE_CHARS:
        return first_line or "New conversation"
    return first_line[: TITLE_CHARS - 1].rstrip() + "…"


class ApprovalBroker:
    """Holds actions that are waiting for the user to say yes or no."""

    def __init__(self) -> None:
        self._pending: dict[str, dict[str, Any]] = {}

    def open(self, info: dict[str, Any]) -> tuple[str, "asyncio.Future[dict[str, bool]]"]:
        approval_id = uuid.uuid4().hex[:12]
        future: asyncio.Future[dict[str, bool]] = asyncio.get_running_loop().create_future()
        self._pending[approval_id] = {**info, "id": approval_id, "future": future}
        return approval_id, future

    def resolve(self, approval_id: str, approve: bool, always: bool = False) -> bool:
        entry = self._pending.get(approval_id)
        if entry is None or entry["future"].done():
            return False
        entry["future"].set_result({"approve": approve, "always": always})
        return True

    def close(self, approval_id: str) -> None:
        self._pending.pop(approval_id, None)

    def pending(self) -> list[dict[str, Any]]:
        return [{k: v for k, v in entry.items() if k != "future"} for entry in self._pending.values()]


class Agent:
    def __init__(
        self,
        *,
        settings: Settings,
        prefs: Prefs,
        store: Store,
        memory: Memory,
        learner: Learner,
        registry: ToolRegistry,
        approvals: ApprovalBroker,
        services: dict[str, Any],
        get_router: Callable[[], ModelRouter],
        spawn: Callable[[Coroutine[Any, Any, Any]], None],
    ):
        self.settings = settings
        self.prefs = prefs
        self.store = store
        self.memory = memory
        self.learner = learner
        self.registry = registry
        self.approvals = approvals
        self.services = services
        self._get_router = get_router
        self._spawn = spawn

    # ----- starting a turn -----------------------------------------------

    def start_turn(
        self,
        conversation_id: str | None,
        text: str = "",
        *,
        regenerate: bool = False,
        edit_message_id: int | None = None,
        channel: str = "app",
    ) -> dict[str, Any]:
        """Validate the request and put the conversation in the right state to be answered."""
        if channel not in ("app", "telegram"):
            raise ValueError("Channel must be app or telegram.")
        text = text.strip()
        if not regenerate:
            if not text:
                raise ValueError("Message is empty.")
            if len(text) > MAX_MESSAGE_CHARS:
                raise ValueError(f"Message is too long (limit {MAX_MESSAGE_CHARS:,} characters).")

        if conversation_id:
            conversation = self.store.get_conversation(conversation_id)
            if conversation is None:
                raise ConversationNotFound(conversation_id)
        elif regenerate or edit_message_id is not None:
            raise ValueError("That needs an existing conversation.")
        else:
            conversation = self.store.create_conversation(make_title(text), source=channel)

        if regenerate:
            messages = self.store.get_messages(conversation["id"])
            if not messages:
                raise ValueError("There is nothing to regenerate.")
            if messages[-1]["role"] == "assistant":
                self.store.delete_messages_from(conversation["id"], messages[-1]["id"])
        elif edit_message_id is not None:
            target = next((m for m in self.store.get_messages(conversation["id"]) if m["id"] == edit_message_id), None)
            if target is None or target["role"] != "user":
                raise ValueError("That message can't be edited.")
            self.store.delete_messages_from(conversation["id"], edit_message_id)
            self.store.add_message(conversation["id"], "user", text)
        else:
            self.store.add_message(conversation["id"], "user", text)
        return self.store.get_conversation(conversation["id"]) or conversation

    # ----- context --------------------------------------------------------

    def build_context(
        self, conversation: dict[str, Any], prefs: dict[str, Any], tool_names: list[str], channel: str = "app"
    ) -> tuple[list[ChatMessage], list[dict[str, Any]], str]:
        """Returns (messages for the model, messages that no longer fit, the user's latest text)."""
        history = self.store.get_messages(conversation["id"])
        selected: list[dict[str, Any]] = []
        total = 0
        for message in reversed(history):
            if len(selected) >= self.settings.max_history_messages:
                break
            size = len(message["content"])
            if selected and total + size > self.settings.max_context_chars:
                break
            selected.append(message)
            total += size
        selected.reverse()
        # A conversation sent to a model should start with the user speaking.
        while selected and selected[0]["role"] != "user":
            selected.pop(0)

        first_id = selected[0]["id"] if selected else 0
        older = [message for message in history if message["id"] < first_id]
        unsummarised = [message for message in older if message["id"] > (conversation.get("summary_upto") or 0)]
        user_text = next((m["content"] for m in reversed(selected) if m["role"] == "user"), "")

        memory_on = prefs["memory_enabled"]
        known = self.memory.context(user_text) if memory_on else MemoryContext()
        recent: list[str] = []
        if memory_on:
            for other in self.store.list_conversations(limit=6):
                if other["id"] != conversation["id"] and len(recent) < 5:
                    recent.append(f"\"{other['title']}\" ({other['updated_at'][:10]})")

        system = build_system_prompt(
            prefs,
            tool_names=tool_names,
            style_rules=known.style,
            memories=known.memories,
            omitted_memories=known.omitted,
            summary=(conversation.get("summary") or "") if older else "",
            recent_titles=recent,
            channel=channel,
        )
        messages = [ChatMessage("system", system)]

        with_tools = [m["id"] for m in selected if m["role"] == "assistant" and any(p["type"] == "tool" for p in m["parts"] or [])]
        replay = set(with_tools[-REPLAY_TURNS:])
        for message in selected:
            if message["role"] == "user":
                messages.append(ChatMessage("user", message["content"]))
                continue
            if message["id"] in replay:
                # Replay earlier tool use faithfully, so the model keeps seeing that
                # actions happen through tools and not by simply saying so.
                steps = [p for p in message["parts"] if p["type"] == "tool" and p["status"] in ("ok", "error", "denied")]
                if steps:
                    calls = [ToolCall(f"call_{p['id']}", p["tool"], json.dumps(p.get("args") or {})) for p in steps]
                    messages.append(ChatMessage("assistant", "", tool_calls=calls))
                    for step, call in zip(steps, calls):
                        shown = "[content omitted]" if step.get("untrusted") else (step.get("result") or step.get("summary") or "")
                        prefix = "" if step["status"] == "ok" else "ERROR: "
                        messages.append(ChatMessage("tool", prefix + shown[:REPLAY_RESULT_CHARS], tool_call_id=call.id))
            if message["content"].strip():
                messages.append(ChatMessage("assistant", message["content"]))
        return messages, unsummarised, user_text

    @staticmethod
    def _shrink(messages: list[ChatMessage], turn_start: int) -> None:
        """Drop history before the current turn and trim long tool results (request was too large)."""
        tail = messages[turn_start:]
        for message in tail:
            if message.role == "tool" and len(message.content) > 1200:
                message.content = message.content[:1200] + "\n[truncated]"
        messages[:] = messages[:1] + tail

    async def _model_events(
        self, messages: list[ChatMessage], schemas: list[dict[str, Any]] | None, prefer: str | None, turn_start: int
    ) -> AsyncIterator[RouterEvent]:
        router = self._get_router()
        try:
            async with aclosing(router.stream_chat(messages, schemas, prefer)) as stream:
                async for event in stream:
                    yield event
            return
        except LLMError as exc:
            if exc.status != 413 or len(messages) <= 2:
                raise
        self._shrink(messages, turn_start)
        yield RouterEvent("status", "That was too large for the model's limit. Retrying with less history.")
        async with aclosing(router.stream_chat(messages, schemas, prefer)) as stream:
            async for event in stream:
                yield event

    # ----- tools ----------------------------------------------------------

    def _approval_reason(self, tool: Tool, prefs: dict[str, Any], ctx: ToolContext, risk: str | None = None) -> str | None:
        """Why this call needs the user's OK, or None if it may simply run."""
        policy = self.registry.policy(tool, prefs)
        risk = risk or tool.risk
        if risk == RISK_SENSITIVE:
            return "This can't easily be undone."
        if policy == "ask":
            return "You've set this action to ask first."
        if risk == RISK_READ:
            return None
        if prefs["ask_every_action"]:
            return "You've asked to approve every action."
        if ctx.tainted:
            return "This task has read outside content, so actions need your OK."
        return None

    async def _run_tool(
        self,
        call: ToolCall,
        tools: dict[str, Tool],
        ctx: ToolContext,
        prefs: dict[str, Any],
        parts: list[dict[str, Any]],
        outcome: dict[str, str],
    ) -> AsyncIterator[dict[str, Any]]:
        tool = tools.get(call.name)
        try:
            raw = json.loads(call.arguments or "{}")
        except json.JSONDecodeError:
            raw = None
        args: dict[str, Any] = {}
        problem: str | None = None
        if tool is None:
            problem = f"There is no tool called '{call.name}'. Available tools: {', '.join(tools) or 'none'}."
        elif raw is None:
            problem = "Invalid arguments: they were not valid JSON."
        else:
            args, invalid = validate_args(tool.parameters, raw)
            problem = f"Invalid arguments: {invalid}." if invalid else None

        risk = tool.risk if tool else RISK_READ
        if not problem and tool is not None:
            if self.registry.policy(tool, prefs) == "off":
                problem = "This tool has been switched off."
            else:
                try:
                    risk = tool.effective_risk(args, ctx)
                except ToolError as exc:
                    problem = str(exc)
                except Exception:
                    log.exception("Tool %s risk assessment crashed", tool.name)
                    problem = "The tool could not assess this action safely; it was not run."

        part: dict[str, Any] = {
            "type": "tool",
            "id": uuid.uuid4().hex[:8],
            "tool": call.name,
            "label": tool.label if tool else call.name,
            "title": tool.describe(args or (raw if isinstance(raw, dict) else {})) if tool else f"Unknown tool “{call.name}”",
            "args": args,
            "risk": risk,
            "status": "running",
        }
        parts.append(part)
        yield {"type": "tool_start", "step": dict(part)}

        result: ToolResult | None = ToolResult(False, problem) if problem else None
        decision = "auto"
        duration_ms = 0
        if result is None and tool is not None:
            reason = self._approval_reason(tool, prefs, ctx, risk)
            if reason:
                can_always = risk != RISK_SENSITIVE and not ctx.tainted and not prefs["ask_every_action"]
                approval_id, future = self.approvals.open(
                    {"tool": tool.name, "title": part["title"], "reason": reason, "conversation_id": ctx.conversation_id}
                )
                part["status"] = "awaiting_approval"
                try:
                    yield {
                        "type": "approval_required",
                        "id": approval_id,
                        "step_id": part["id"],
                        "label": tool.label,
                        "title": part["title"],
                        "reason": reason,
                        "can_always": can_always,
                    }
                    try:
                        answer = await asyncio.wait_for(future, APPROVAL_TIMEOUT)
                    except asyncio.TimeoutError:
                        answer = None
                finally:
                    self.approvals.close(approval_id)  # also runs if the user presses Stop while it waits
                if answer and answer["approve"]:
                    decision = "approved"
                    if answer["always"] and can_always:
                        self.prefs.update({"tool_policy": {tool.name: "allow"}})
                elif answer:
                    decision = "denied"
                    result = ToolResult(False, "The user declined this action.", summary="Declined by you")
                else:
                    decision = "expired"
                    result = ToolResult(False, "The approval request expired without an answer.", summary="Approval expired")
                yield {"type": "approval_resolved", "id": approval_id, "step_id": part["id"], "decision": decision}

            if result is None:
                part["status"] = "running"
                started = time.perf_counter()
                try:
                    result = await asyncio.wait_for(tool.handler(args, ctx), tool.timeout)
                except ToolError as exc:
                    result = ToolResult(False, str(exc))
                except asyncio.TimeoutError:
                    result = ToolResult(False, f"Timed out after {tool.timeout:.0f} seconds.")
                except Exception as exc:  # a tool bug must not take the whole turn down
                    log.exception("Tool %s crashed", tool.name)
                    result = ToolResult(False, f"The tool failed unexpectedly ({type(exc).__name__}).")
                duration_ms = int((time.perf_counter() - started) * 1000)

        assert result is not None
        status = "ok" if result.ok else ("denied" if decision in ("denied", "expired") else "error")
        untrusted = bool(result.ok and tool is not None and (result.untrusted or tool.untrusted_output))
        if untrusted:
            ctx.tainted = True
        part.update(
            status=status,
            summary=result.summary,
            result=result.text[:1500],
            decision=decision,
            duration_ms=duration_ms,
            data=result.data,
            untrusted=untrusted,
        )
        self.store.add_tool_run(
            run_id=ctx.run_id,
            conversation_id=ctx.conversation_id,
            tool=call.name,
            title=part["title"],
            args=args,
            risk=part["risk"],
            decision=decision,
            status=status,
            summary=result.summary,
            duration_ms=duration_ms,
        )
        yield {"type": "tool_end", "step": dict(part)}
        outcome["text"] = (result.text if result.ok else f"ERROR: {result.text}")[:MAX_TOOL_RESULT_CHARS]

    # ----- the turn -------------------------------------------------------

    def _save(self, conversation_id: str, parts: list[dict[str, Any]], model: str | None, note: str | None = None) -> dict[str, Any]:
        for part in parts:
            if part["type"] == "tool" and part["status"] in ("running", "awaiting_approval"):
                part.update(status="cancelled", summary="Stopped before it finished")
        if note:
            parts.append({"type": "text", "text": note})
        content = "\n\n".join(part["text"].strip() for part in parts if part["type"] == "text")
        return self.store.add_message(conversation_id, "assistant", content, model, parts)

    async def run_turn(
        self, conversation: dict[str, Any], prefer: str | None = None, channel: str = "app"
    ) -> AsyncIterator[dict[str, Any]]:
        """Answer the latest user message. Yields events for the interface."""
        if channel not in ("app", "telegram"):
            raise ValueError("Channel must be app or telegram.")
        conversation_id = conversation["id"]
        prefs = self.prefs.all()
        ctx = ToolContext(conversation_id, uuid.uuid4().hex[:12], self.services, channel=channel)
        tools = {tool.name: tool for tool in self.registry.enabled(prefs)}
        schemas = [tool.schema() for tool in tools.values()] or None
        asked = [m["id"] for m in self.store.get_messages(conversation_id) if m["role"] == "user"]
        yield {"type": "conversation", "conversation": conversation, "user_message_id": asked[-1] if asked else None}

        parts: list[dict[str, Any]] = []
        model: str | None = None
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "requests": 0}
        saved = False
        try:
            try:
                messages, dropped, user_text = self.build_context(conversation, prefs, list(tools), channel=channel)
                turn_start = len(messages) - 1
                max_steps = prefs["max_steps"]
                for step in range(max_steps + 1):
                    out_of_steps = step == max_steps
                    if out_of_steps:
                        messages.append(ChatMessage("user", STEP_LIMIT_NOTE))
                    calls: list[ToolCall] = []
                    text: list[str] = []
                    async with aclosing(
                        self._model_events(messages, None if out_of_steps else schemas, prefer, turn_start)
                    ) as events:
                        async for event in events:
                            if event.kind == "model":
                                if event.value != model:
                                    model = event.value
                                    yield {"type": "model", "model": model}
                            elif event.kind == "token":
                                text.append(event.value)
                                yield {"type": "token", "text": event.value}
                            elif event.kind == "tool_call" and event.tool_call:
                                calls.append(event.tool_call)
                            elif event.kind == "status":
                                yield {"type": "status", "text": event.value}
                            elif event.kind == "usage" and event.data:
                                usage["prompt_tokens"] += event.data.get("prompt_tokens", 0)
                                usage["completion_tokens"] += event.data.get("completion_tokens", 0)
                    usage["requests"] += 1
                    segment = "".join(text)
                    if segment.strip():
                        parts.append({"type": "text", "text": segment})
                    if not calls:
                        break
                    messages.append(ChatMessage("assistant", segment, tool_calls=calls))
                    for call in calls:
                        outcome: dict[str, str] = {}
                        async with aclosing(self._run_tool(call, tools, ctx, prefs, parts, outcome)) as steps:
                            async for update in steps:
                                yield update
                        messages.append(ChatMessage("tool", outcome["text"], tool_call_id=call.id))
                        prefs = self.prefs.all()  # "always allow" may just have changed a permission
            except LLMError as exc:
                if parts:
                    self._save(conversation_id, parts, model, "*[Response interrupted]*")
                    saved = True
                yield {"type": "error", "message": str(exc)}
                return

            message = self._save(conversation_id, parts, model)
            saved = True
            yield {"type": "done", "message": message, "usage": usage}

            used_remember = any(p["type"] == "tool" and p["tool"] == "remember" and p["status"] == "ok" for p in parts)
            if prefs["memory_enabled"] and prefs["auto_learn"] and not used_remember:
                self._spawn(self.learner.reflect(conversation_id, user_text, message["content"]))
            if len(dropped) >= SUMMARISE_AFTER:
                self._spawn(self.learner.summarise(conversation_id, dropped))
        finally:
            # Reached without saving if the user pressed Stop mid-reply.
            if not saved and parts:
                self._save(conversation_id, parts, model, "*[Stopped]*")
