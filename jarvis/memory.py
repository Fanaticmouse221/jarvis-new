"""Long-term memory: what JARVIS knows about the user, and how it learns it.

Three things live here:

* `Memory`   the store's rules: cleaning, duplicate detection, which memories go
             into each reply's context.
* `Learner`  after each exchange, a background pass that asks a model to pull
             out anything durable the user said, and keeps a rolling summary of
             long conversations so earlier parts aren't lost.
* helpers    secret detection and tolerant JSON parsing.

Design choice: while everything known fits in a small budget, all of it is
given to the model on every turn, so nothing can be missed by a bad search.
Search-based selection only starts once memory outgrows that budget.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Callable

from jarvis.llm import ChatMessage, LLMError, ModelRouter
from jarvis.llm.fake import REFLECT_MARKER, SUMMARY_MARKER
from jarvis.storage import MEMORY_KINDS, Store

log = logging.getLogger("jarvis.memory")

MAX_MEMORY_CHARS = 400
CONTEXT_BUDGET = 1800  # characters of general memories placed in each prompt
STYLE_BUDGET = 700  # characters of standing instructions placed in each prompt
SIMILARITY = 0.86  # above this, two memories are treated as the same fact
SUMMARISE_AFTER = 6  # unsummarised messages that have scrolled out of context

KIND_ORDER = {kind: index for index, kind in enumerate(("preference", "personal", "project", "note"))}

_SECRET_PATTERNS = [
    re.compile(r"\b(gsk|sk|pk|rk|xox[bap])[-_][A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"\b(?:\d[ -]?){13,19}\b"),
    re.compile(r"\b(pass(word|code)?|pin|secret|api[ _-]?key)\b\s*(is|=|:)\s*\S+", re.I),
]

# A cheap test for "might contain something worth remembering", so the extraction
# model is only called when the user talked about themselves or gave an instruction.
_LEARN_HINT = re.compile(
    r"\b(i'm|im|i am|i've|i have|i'd|i'll|i was|i got|my|mine|myself|our|call me|remember|prefer|"
    r"favourite|favorite|from now on|instead|actually|stop|don't|dont|always|never|"
    r"i (?:prefer|like|love|enjoy|hate|dislike|want|need|use|live|work|study|play|go|usually|can't|cannot))\b",
    re.I,
)

REFLECT_PROMPT = f"""{REFLECT_MARKER} of a personal assistant called JARVIS.
Read the user's latest message and decide whether it contains anything durable worth remembering in future conversations:
- preference: lasting likes, dislikes and ways they want things done
- personal: facts about them (name, where they live, what they study, people in their life)
- project: ongoing work, goals, deadlines
- style: how they want JARVIS to behave or respond (tone, length, form of address), including corrections
- note: anything else worth keeping

Rules:
- Only store what the user stated about themselves or asked for. Ignore questions, one-off requests, small talk and anything JARVIS said.
- Never store passwords, keys, card numbers or similar secrets.
- Don't repeat an existing memory. If the message changes or contradicts one, return an update for its number instead of adding.
- Write each memory as one short third-person sentence ("Prefers...", "Is studying...").
- At most 3 items. Most messages contain nothing durable.

Reply with JSON only, no other text:
{{"add": [{{"kind": "preference", "content": "..."}}], "update": [{{"id": 12, "content": "..."}}]}}
If nothing is worth remembering: {{"add": [], "update": []}}"""

SUMMARY_PROMPT = f"""{SUMMARY_MARKER} for a personal assistant called JARVIS.
Write a summary of the conversation so far in at most 90 words. Keep: what the user wanted, decisions made, key facts and figures, and anything left unfinished. Plain prose, no preamble."""


def looks_secret(text: str) -> bool:
    return any(pattern.search(text) for pattern in _SECRET_PATTERNS)


def clean_content(text: Any) -> str:
    if not isinstance(text, str):
        raise ValueError("Memory content must be text.")
    text = " ".join(text.split())
    if len(text) < 3:
        raise ValueError("That memory is empty.")
    if len(text) > MAX_MEMORY_CHARS:
        raise ValueError(f"That memory is too long (limit {MAX_MEMORY_CHARS} characters). Keep one fact per memory.")
    if looks_secret(text):
        raise ValueError("That looks like a password, key or card number. JARVIS doesn't store those.")
    return text


def _normalise(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", text.lower()).split())


def parse_json_object(text: str) -> dict[str, Any]:
    """Pull the first JSON object out of a model reply (tolerates code fences and chatter)."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return {}
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


@dataclass
class MemoryContext:
    style: list[dict[str, Any]] = field(default_factory=list)
    memories: list[dict[str, Any]] = field(default_factory=list)
    omitted: int = 0


class Memory:
    def __init__(self, store: Store, on_change: Callable[[str, dict[str, Any]], None] | None = None):
        self.store = store
        self._on_change = on_change

    def _changed(self, action: str, memory: dict[str, Any]) -> None:
        if self._on_change:
            self._on_change(action, memory)

    def find_similar(self, content: str) -> dict[str, Any] | None:
        target = _normalise(content)
        best: tuple[float, dict[str, Any]] | None = None
        for memory in self.store.list_memories():
            other = _normalise(memory["content"])
            score = 1.0 if other == target else SequenceMatcher(None, target, other).ratio()
            if score >= SIMILARITY and (best is None or score > best[0]):
                best = (score, memory)
        return best[1] if best else None

    def add(
        self, content: str, kind: str = "note", source: str = "told", conversation_id: str | None = None
    ) -> tuple[dict[str, Any], bool]:
        """Store a memory. Returns (memory, created). A near-duplicate is refreshed, not added."""
        content = clean_content(content)
        if kind not in MEMORY_KINDS:
            kind = "note"
        existing = self.find_similar(content)
        if existing:
            updated = self.store.update_memory(existing["id"], content=content) or existing
            return updated, False
        memory = self.store.add_memory(content, kind, source, conversation_id)
        self._changed("learned" if source == "learned" else "saved", memory)
        return memory, True

    def replace(self, memory_id: int, content: str | None = None, kind: str | None = None, pinned: bool | None = None) -> dict[str, Any] | None:
        if self.store.get_memory(memory_id) is None:
            return None
        if content is not None:
            content = clean_content(content)
        if kind is not None and kind not in MEMORY_KINDS:
            raise ValueError(f"Kind must be one of: {', '.join(MEMORY_KINDS)}.")
        memory = self.store.update_memory(memory_id, content=content, kind=kind, pinned=pinned)
        if memory and content is not None:
            self._changed("updated", memory)
        return memory

    def forget(self, memory_id: int) -> dict[str, Any] | None:
        memory = self.store.get_memory(memory_id)
        if memory and self.store.delete_memory(memory_id):
            self._changed("forgotten", memory)
            return memory
        return None

    def recall(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        hits = self.store.search_memories(query, limit) if query.strip() else self.store.list_memories()[:limit]
        self.store.touch_memories([hit["id"] for hit in hits])
        return hits

    def context(self, query: str) -> MemoryContext:
        """Choose the memories that accompany a reply."""
        everything = self.store.list_memories()
        result = MemoryContext()
        used = 0
        for memory in everything:
            if memory["kind"] == "style" and used + len(memory["content"]) <= STYLE_BUDGET:
                result.style.append(memory)
                used += len(memory["content"])
        general = [memory for memory in everything if memory["kind"] != "style"]
        general.sort(key=lambda m: KIND_ORDER.get(m["kind"], 9))  # stable: keeps pinned/recent order within a kind

        if sum(len(memory["content"]) for memory in general) <= CONTEXT_BUDGET:
            result.memories = general
            return result

        # Too much to include everything: pinned first, then what matches this message, then recent basics.
        relevant = self.store.search_memories(query, 8) if query.strip() else []
        relevant_ids = [memory["id"] for memory in relevant]
        ranked = (
            [m for m in general if m["pinned"]]
            + relevant
            + [m for m in general if m["kind"] in ("preference", "personal")]
            + general
        )
        chosen: dict[int, dict[str, Any]] = {}
        size = 0
        for memory in ranked:
            if memory["id"] in chosen or memory["kind"] == "style":
                continue
            if size + len(memory["content"]) > CONTEXT_BUDGET:
                continue
            chosen[memory["id"]] = memory
            size += len(memory["content"])
        result.memories = sorted(chosen.values(), key=lambda m: KIND_ORDER.get(m["kind"], 9))
        result.omitted = len(general) - len(chosen)
        self.store.touch_memories([mid for mid in relevant_ids if mid in chosen])
        return result

    def export(self) -> dict[str, Any]:
        return {"format": "jarvis-memory-v1", "memories": self.store.list_memories()}


async def complete(router: ModelRouter, messages: list[ChatMessage], prefer: str | None = None) -> str:
    """Run a prompt to completion and return its text (no tools)."""
    parts: list[str] = []
    async for event in router.stream_chat(messages, None, prefer):
        if event.kind == "token":
            parts.append(event.value)
    return "".join(parts)


class Learner:
    """Background learning: memory extraction and conversation summaries.

    Uses the last model in the list where possible. On Groq each model has its
    own rate limit, so this doesn't eat into the main model's allowance.
    """

    def __init__(self, memory: Memory, get_router: Callable[[], ModelRouter]):
        self.memory = memory
        self.store = memory.store
        self._get_router = get_router

    def _side_model(self) -> tuple[ModelRouter, str | None]:
        router = self._get_router()
        return router, (router.labels[-1] if router.labels else None)

    @staticmethod
    def worth_reflecting(user_text: str) -> bool:
        return len(user_text.strip()) >= 12 and bool(_LEARN_HINT.search(user_text))

    async def reflect(self, conversation_id: str, user_text: str, assistant_text: str) -> list[dict[str, Any]]:
        """Extract durable facts from one exchange. Returns the changes made."""
        if not self.worth_reflecting(user_text):
            return []
        router, prefer = self._side_model()
        listing = "\n".join(f"#{m['id']} ({m['kind']}) {m['content']}" for m in self.store.list_memories())[:1500]
        prompt = (
            f"Existing memories:\n{listing or '(none)'}\n\n"
            f"User message:\n{user_text[:1500]}\n\n"
            f"Assistant reply:\n{assistant_text[:400]}"
        )
        try:
            reply = await complete(router, [ChatMessage("system", REFLECT_PROMPT), ChatMessage("user", prompt)], prefer)
        except LLMError as exc:
            log.info("Memory extraction skipped: %s", exc)
            return []

        data = parse_json_object(reply)
        changes: list[dict[str, Any]] = []
        for item in (data.get("update") or [])[:3]:
            try:
                memory = self.memory.replace(int(item["id"]), content=item["content"])
            except (KeyError, TypeError, ValueError):
                continue
            if memory:
                changes.append({"action": "updated", "memory": memory})
        for item in (data.get("add") or [])[:3]:
            try:
                memory, created = self.memory.add(item["content"], item.get("kind", "note"), "learned", conversation_id)
            except (KeyError, TypeError, ValueError):
                continue
            if created:
                changes.append({"action": "learned", "memory": memory})
        for change in changes:
            self.store.add_tool_run(
                run_id="learning",
                conversation_id=conversation_id,
                tool="memory.learn",
                title=("Learned: " if change["action"] == "learned" else "Updated memory: ") + change["memory"]["content"],
                args={},
                risk="act",
                decision="auto",
                status="ok",
                summary=f"Memory #{change['memory']['id']} ({change['memory']['kind']})",
            )
        return changes

    async def summarise(self, conversation_id: str, dropped: list[dict[str, Any]]) -> str | None:
        """Fold messages that no longer fit in context into the conversation's rolling summary."""
        conversation = self.store.get_conversation(conversation_id)
        if conversation is None or not dropped:
            return None
        transcript = "\n".join(
            f"{'User' if message['role'] == 'user' else 'JARVIS'}: {message['content'][:600]}" for message in dropped
        )[:4000]
        prompt = f"Previous summary:\n{conversation.get('summary') or '(none)'}\n\nNew messages:\n{transcript}"
        router, prefer = self._side_model()
        try:
            summary = await complete(router, [ChatMessage("system", SUMMARY_PROMPT), ChatMessage("user", prompt)], prefer)
        except LLMError as exc:
            log.info("Conversation summary skipped: %s", exc)
            return None
        summary = " ".join(summary.split())[:900]
        if summary:
            self.store.set_summary(conversation_id, summary, dropped[-1]["id"])
        return summary or None
