"""Owner-only Telegram chat using outbound long polling and the normal agent."""

from __future__ import annotations

import asyncio
import html
import logging
import re
import secrets
import time
from contextlib import aclosing, suppress
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING
from urllib.parse import urlsplit

import httpx

from jarvis.agent import make_title

if TYPE_CHECKING:
    from jarvis.runtime import Runtime


HELP = "Send me a text message. /new starts a fresh conversation; /stop stops the current reply; /help shows this help."
TOKEN_RE = re.compile(r"^[0-9]{5,20}:[A-Za-z0-9_-]{20,200}$")
_MARKDOWN = re.compile(r"```(?:[^\n`]*\n)?([\s\S]*?)```|`([^`\n]+)`|\[([^\]\n]+)\]\(([^\s)]+)\)|\*\*([^*\n]+)\*\*|__([^_\n]+)__|(?<!\w)\*([^*\n]+)\*|(?<!\w)_([^_\n]+)_(?!\w)")


class _HideBotTokens(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = re.sub(r"/bot[0-9]+:[A-Za-z0-9_-]+", "/bot[redacted]", record.getMessage())
        record.args = ()
        return True


# httpx INFO otherwise includes the authentication token, which is part of the URL.
logging.getLogger("httpx").addFilter(_HideBotTokens())


class TelegramError(Exception):
    """Safe, token-free API failure suitable for the local Settings screen."""

    def __init__(self, status: int = 0, retry_after: float = 0):
        self.status = status
        self.retry_after = retry_after
        message = {
            401: "Telegram token rejected. Copy the token from BotFather again.",
            409: "Another program is using this bot token. Close it before reconnecting.",
            403: "Telegram could not deliver the message. Open your bot and check it is not blocked.",
            429: "Telegram is busy. Retrying shortly.",
            400: "Telegram could not accept that message.",
        }.get(status, "Could not connect to Telegram. Check your internet connection.")
        super().__init__(message)


def markdown_to_html(text: str) -> str:
    """A small, deliberately restricted Markdown renderer; raw HTML is always escaped."""
    out: list[str] = []
    end = 0
    for match in _MARKDOWN.finditer(text):
        out.append(html.escape(text[end:match.start()], quote=False))
        fenced, code, label, url, bold, under_bold, italic, under_italic = match.groups()
        if fenced is not None:
            out.append(f"<pre>{html.escape(fenced, quote=False)}</pre>")
        elif code is not None:
            out.append(f"<code>{html.escape(code, quote=False)}</code>")
        elif label is not None:
            try:
                safe_link = urlsplit(url).scheme.lower() in ("http", "https")
            except ValueError:
                safe_link = False
            if safe_link:
                out.append(f'<a href="{html.escape(url, quote=True)}">{html.escape(label, quote=False)}</a>')
            else:
                out.append(html.escape(match.group(), quote=False))
        else:
            tag, value = ("b", bold or under_bold) if bold or under_bold else ("i", italic or under_italic)
            out.append(f"<{tag}>{html.escape(value or '', quote=False)}</{tag}>")
        end = match.end()
    out.append(html.escape(text[end:], quote=False))
    return "".join(out)


def split_message(text: str, limit: int = 3800) -> list[str]:
    """Split before rendering, favouring paragraphs and bounding UTF-16 length too."""
    if not text:
        return []
    chunks: list[str] = []
    while text:
        end, units = 0, 0
        for character in text:
            units += 2 if ord(character) > 0xFFFF else 1
            if units > limit:
                break
            end += 1
        if end < len(text):
            paragraph = text.rfind("\n\n", 0, end)
            line = text.rfind("\n", 0, end)
            space = text.rfind(" ", 0, end)
            preferred = paragraph + 2 if paragraph >= end // 3 else line + 1 if line >= end // 3 else space + 1
            if preferred >= end // 3:
                end = preferred
        end = max(1, end)
        # Escaping can expand the wire text. Stay below the limit even before parsing.
        while len(markdown_to_html(text[:end])) > 4096 and end > 1:
            end //= 2
        chunks.append(text[:end])
        text = text[end:]
    return chunks


class TelegramService:
    def __init__(self, runtime: Runtime, token: str = "", api_base: str = "https://api.telegram.org", *, transport: httpx.AsyncBaseTransport | None = None):
        self.runtime = runtime
        self.token = token
        self.api_base = api_base.rstrip("/")
        self.transport = transport
        self._client: httpx.AsyncClient | None = None
        self._poll_task: asyncio.Task[Any] | None = None
        self._worker_task: asyncio.Task[Any] | None = None
        self._turn_task: asyncio.Task[Any] | None = None
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=30)
        self._approvals: dict[str, tuple[int, int]] = {}
        self._started = False
        self._running = False
        self._generation = 0
        self._state = "disabled" if not token else "stopped"
        self.last_error = ""
        self.username = runtime.store.get_setting("telegram_username", "")
        self._rotate_code()

    @property
    def owner(self) -> int | None:
        return self.runtime.store.get_setting("telegram_owner")

    def _rotate_code(self) -> None:
        previous = getattr(self, "_pairing_code", None)
        self._pairing_code = f"{secrets.randbelow(1_000_000):06d}"
        while self._pairing_code == previous:
            self._pairing_code = f"{secrets.randbelow(1_000_000):06d}"
        self._wrong: dict[int, int] = {}
        self._wrong_total = 0

    def status(self) -> dict[str, Any]:
        linked = self.owner is not None
        return {
            "state": self._state, "enabled": bool(self.token), "linked": linked,
            "username": self.username, "bot_username": self.username,
            "pairing_code": self._pairing_code if self.token and not linked else None,
            "token_hint": f"…{self.token[-4:]}" if self.token else "",
            "last_error": self.last_error,
        }

    async def _api(self, method: str, data: dict[str, Any] | None = None, *, token: str | None = None) -> Any:
        selected = self.token if token is None else token
        if not selected:
            raise TelegramError(401)
        own_client = self._client is None
        client = self._client or httpx.AsyncClient(transport=self.transport, timeout=httpx.Timeout(35, connect=10), follow_redirects=False)
        try:
            try:
                response = await client.post(f"{self.api_base}/bot{selected}/{method}", json=data or {})
                payload = response.json()
            except (httpx.HTTPError, ValueError):
                raise TelegramError() from None
            if not isinstance(payload, dict):
                raise TelegramError()
            if response.status_code >= 400 or not payload.get("ok"):
                code = payload.get("error_code", response.status_code)
                retry = (payload.get("parameters") or {}).get("retry_after", 0)
                raise TelegramError(code if isinstance(code, int) else 0, min(float(retry), 60) if isinstance(retry, (int, float)) else 0)
            return payload.get("result")
        finally:
            if own_client:
                await client.aclose()

    async def verify_token(self, token: str) -> dict[str, Any]:
        token = token.strip()
        if not TOKEN_RE.fullmatch(token):
            raise ValueError("That doesn't look like a complete Telegram bot token.")
        bot = await self._api("getMe", token=token)
        if not isinstance(bot, dict) or not bot.get("is_bot") or not isinstance(bot.get("id"), int):
            raise TelegramError(401)
        return bot

    def _save_bot(self, bot: dict[str, Any]) -> None:
        old_id = self.runtime.store.get_setting("telegram_bot_id")
        if old_id != bot["id"]:
            self._generation += 1
            self.runtime.store.set_setting("telegram_owner", None)
            self.runtime.store.set_setting("telegram_conversation", None)
            self.runtime.store.set_setting("telegram_offset", 0)
            self._rotate_code()
        self.username = bot.get("username", "")
        self.runtime.store.set_setting("telegram_bot_id", bot["id"])
        self.runtime.store.set_setting("telegram_username", self.username)

    async def configure(self, token: str, bot: dict[str, Any] | None = None) -> None:
        token = token.strip()
        bot = bot or await self.verify_token(token)
        restart = self._started
        self._generation += 1
        await self.stop()
        self.token = token
        self._save_bot(bot)
        self.last_error = ""
        self._state = "stopped"
        if restart:
            await self.start()

    async def start(self) -> None:
        self._started = True
        if self._running or not self.token:
            return
        self._running = True
        self._state = "connecting"
        self._client = httpx.AsyncClient(transport=self.transport, timeout=httpx.Timeout(35, connect=10), follow_redirects=False)
        self._worker_task = asyncio.create_task(self._worker(), name="telegram-worker")
        self._poll_task = asyncio.create_task(self._poll(), name="telegram-poll")

    async def stop(self) -> None:
        self._started = False
        self._running = False
        # Cancelling the worker propagates to the turn it awaits. Cancelling both
        # would inject a second cancellation into the turn's cleanup block.
        tasks = [task for task in (self._poll_task, self._worker_task) if task and task is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._poll_task = self._worker_task = self._turn_task = None
        self._clear_queue()
        self._approvals.clear()
        if self._client:
            await self._client.aclose()
            self._client = None
        self._state = "stopped" if self.token else "disabled"

    async def unlink(self) -> None:
        restart = self._started
        self._generation += 1
        await self.stop()
        self.runtime.store.set_setting("telegram_owner", None)
        self.runtime.store.set_setting("telegram_conversation", None)
        self._rotate_code()
        if restart:
            await self.start()

    async def remove(self) -> None:
        started = self._started
        self._generation += 1
        await self.stop()
        self.token = ""
        self.username = ""
        self.last_error = ""
        for key in ("telegram_owner", "telegram_conversation", "telegram_bot_id", "telegram_username"):
            self.runtime.store.set_setting(key, None)
        self._rotate_code()
        self._state = "disabled"
        # Disabling a bot does not end the application's lifespan. A replacement
        # token entered later must start polling without restarting the PC app.
        self._started = started

    def _clear_queue(self) -> None:
        while not self._queue.empty():
            self._queue.get_nowait()
            self._queue.task_done()

    async def _poll(self) -> None:
        delay = 2.0
        verified = False
        while self._running:
            try:
                if not verified:
                    try:
                        self._save_bot(await self.verify_token(self.token))
                    except ValueError:
                        raise TelegramError(401) from None
                    verified = True
                self._state = "linked" if self.owner is not None else "pairing"
                updates = await self._api("getUpdates", {
                    "offset": self.runtime.store.get_setting("telegram_offset", 0),
                    "timeout": 25, "allowed_updates": ["message", "callback_query"],
                })
                if not isinstance(updates, list):
                    raise TelegramError()
                self.last_error = ""
                delay = 2.0
                for update in updates:
                    if not isinstance(update, dict) or not isinstance(update.get("update_id"), int):
                        continue
                    offset = self.runtime.store.get_setting("telegram_offset", 0)
                    if update["update_id"] < offset:
                        continue
                    # Claim before side effects: restart must not repeat an action.
                    self.runtime.store.set_setting("telegram_offset", update["update_id"] + 1)
                    await self.handle_update(update)
                if not updates:
                    await asyncio.sleep(0.05)  # mock/local APIs may return immediately
            except TelegramError as exc:
                self.last_error = str(exc)
                self._state = "error"
                if exc.status in (401, 409):
                    self._running = False
                    if self._worker_task:
                        self._worker_task.cancel()
                    return
                await asyncio.sleep(max(delay, exc.retry_after))
                delay = min(delay * 2, 60)
            except Exception:
                # Never expose request URLs or payloads (the bot token is in the
                # URL). One malformed update must not silently kill polling.
                self.last_error = "Telegram hit an unexpected error. Retrying shortly."
                self._state = "error"
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)

    async def send_text(self, chat_id: int, text: str, *, markup: dict[str, Any] | None = None, expected_generation: int | None = None) -> list[dict[str, Any]]:
        sent = []
        for index, chunk in enumerate(split_message(text)):
            if expected_generation is not None and expected_generation != self._generation:
                return sent
            data: dict[str, Any] = {"chat_id": chat_id, "text": markdown_to_html(chunk), "parse_mode": "HTML", "link_preview_options": {"is_disabled": True}}
            if markup and index == 0:
                data["reply_markup"] = markup
            try:
                sent.append(await self._api("sendMessage", data))
            except TelegramError as exc:
                if exc.status != 400:
                    raise
                if expected_generation is not None and expected_generation != self._generation:
                    return sent
                data.pop("parse_mode")
                data["text"] = chunk
                sent.append(await self._api("sendMessage", data))
        return sent

    async def handle_update(self, update: dict[str, Any]) -> None:
        callback = update.get("callback_query")
        if isinstance(callback, dict):
            await self._callback(callback)
            return
        message = update.get("message")
        if not isinstance(message, dict):
            return
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if chat.get("type") != "private" or not isinstance(chat_id, int):
            return
        sender = message.get("from") or {}
        if sender.get("is_bot") or sender.get("id") != chat_id:
            return
        text = message.get("text", "")
        if not isinstance(text, str):
            text = ""
        if self.owner is None:
            if self._wrong.get(chat_id, 0) >= 5:
                return
            candidate = text.strip()
            if not re.fullmatch(r"[0-9]{6}", candidate):
                return
            if secrets.compare_digest(candidate, self._pairing_code):
                self.runtime.store.set_setting("telegram_owner", chat_id)
                self._state = "linked"
                await self.send_text(chat_id, "Phone linked. " + HELP)
            else:
                self._wrong[chat_id] = self._wrong.get(chat_id, 0) + 1
                self._wrong_total += 1
                if self._wrong_total >= 10:
                    self._rotate_code()
            return
        if chat_id != self.owner:
            return
        command = text.split()[0].split("@")[0].lower() if text.strip() else ""
        if command == "/stop":
            self._clear_queue()
            if self._turn_task:
                self._turn_task.cancel()
            await self.send_text(chat_id, "Stopped. Queued messages cleared.")
            return
        if command in ("/start", "/help"):
            await self.send_text(chat_id, HELP)
            return
        if not text.strip():
            await self.send_text(chat_id, "I can read text messages here. Voice notes, photos and files aren't supported yet.")
            return
        try:
            self._queue.put_nowait(message)
        except asyncio.QueueFull:
            await self.send_text(chat_id, "I have too many messages queued. Wait for a reply, or send /stop to clear them.")

    async def _callback(self, callback: dict[str, Any]) -> None:
        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        owner = self.owner
        if owner is None or chat.get("type") != "private" or chat.get("id") != owner or (callback.get("from") or {}).get("id") != owner:
            return
        data = callback.get("data", "")
        if not isinstance(data, str) or not re.fullmatch(r"jarvis:[a-f0-9]{12}:[yn]", data):
            return
        _, approval_id, decision = data.split(":")
        registered = self._approvals.get(approval_id)
        if registered != (owner, message.get("message_id")):
            return
        approved = decision == "y"
        resolved = self.runtime.approvals.resolve(approval_id, approved)
        self._approvals.pop(approval_id, None)
        outcome = ("Allowed." if approved else "Not allowed.") if resolved else "This approval has expired."
        await self._api("answerCallbackQuery", {"callback_query_id": callback.get("id"), "text": outcome})
        await self._api("editMessageText", {"chat_id": owner, "message_id": message["message_id"], "text": outcome, "reply_markup": {"inline_keyboard": []}})

    def _conversation(self, text: str = "Telegram conversation") -> dict[str, Any]:
        store = self.runtime.store
        conversation_id = store.get_setting("telegram_conversation")
        conversation = store.get_conversation(conversation_id) if conversation_id else None
        if conversation:
            try:
                last = datetime.fromisoformat(conversation["updated_at"].replace("Z", "+00:00"))
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                if time.time() - last.timestamp() >= 8 * 3600:
                    conversation = None
            except (ValueError, TypeError):
                conversation = None
        if conversation is None:
            conversation = store.create_conversation(make_title(text), source="telegram")
            store.set_setting("telegram_conversation", conversation["id"])
        return conversation

    async def _typing(self, chat_id: int) -> None:
        while True:
            with suppress(TelegramError):
                await self._api("sendChatAction", {"chat_id": chat_id, "action": "typing"})
            await asyncio.sleep(4)

    async def _turn(self, message: dict[str, Any]) -> None:
        chat_id, text = message["chat"]["id"], message["text"]
        if text.split()[0].split("@")[0].lower() == "/new":
            self.runtime.store.set_setting("telegram_conversation", None)
            await self.send_text(chat_id, "Fresh conversation. What shall we do?")
            return
        conversation = self._conversation(text)
        if conversation["id"] in self.runtime.active:
            await self.send_text(chat_id, "This conversation is already answering on the PC. Please wait for it to finish.")
            return
        self.runtime.active.add(conversation["id"])
        typing = asyncio.create_task(self._typing(chat_id))
        turn_approvals: set[str] = set()
        try:
            conversation = self.runtime.agent.start_turn(conversation["id"], text, channel="telegram")
            async with aclosing(self.runtime.agent.run_turn(conversation, channel="telegram")) as events:
                async for event in events:
                    if event["type"] == "approval_required":
                        approval_id = event["id"]
                        turn_approvals.add(approval_id)
                        sent = await self.send_text(chat_id, f"Allow: {event['title']}?\n{event['reason']}", markup={"inline_keyboard": [[
                            {"text": "Allow", "callback_data": f"jarvis:{approval_id}:y"},
                            {"text": "Don't allow", "callback_data": f"jarvis:{approval_id}:n"},
                        ]]})
                        self._approvals[approval_id] = (chat_id, sent[0]["message_id"])
                    elif event["type"] == "approval_resolved":
                        registered = self._approvals.pop(event["id"], None)
                        if registered:
                            with suppress(TelegramError):
                                await self._api("editMessageText", {"chat_id": registered[0], "message_id": registered[1], "text": f"Approval {event['decision']}.", "reply_markup": {"inline_keyboard": []}})
                    elif event["type"] == "done":
                        await self.send_text(chat_id, event["message"]["content"] or "Done. You can see the action details on the PC.")
                    elif event["type"] == "error":
                        await self.send_text(chat_id, event["message"])
        finally:
            self.runtime.active.discard(conversation["id"])
            typing.cancel()
            await asyncio.gather(typing, return_exceptions=True)
            for approval_id in turn_approvals:
                registered = self._approvals.pop(approval_id, None)
                if registered:
                    with suppress(TelegramError):
                        await self._api("editMessageText", {"chat_id": registered[0], "message_id": registered[1], "text": "This approval has ended.", "reply_markup": {"inline_keyboard": []}})

    async def _worker(self) -> None:
        while self._running:
            message = await self._queue.get()
            try:
                if message["chat"]["id"] != self.owner:
                    continue
                self._turn_task = asyncio.create_task(self._turn(message))
                try:
                    await self._turn_task
                except asyncio.CancelledError:
                    if not self._running:
                        raise
                except (TelegramError, ValueError) as exc:
                    self.last_error = str(exc)
                    with suppress(TelegramError):
                        await self.send_text(message["chat"]["id"], str(exc))
                except Exception:
                    self.last_error = "The Telegram reply failed unexpectedly. Please try again."
                    with suppress(TelegramError):
                        await self.send_text(message["chat"]["id"], self.last_error)
            finally:
                self._turn_task = None
                self._queue.task_done()

    async def test_message(self) -> dict[str, Any]:
        if self.owner is None:
            raise ValueError("Link your phone first by sending the pairing code to your bot.")
        await self.send_text(self.owner, "JARVIS phone link is working. Systems online.")
        return {"ok": True}

    async def send_reminder(self, text: str, expected_owner: int | None = None) -> bool:
        owner, generation = self.owner, self._generation
        if not self.token or owner is None or (expected_owner is not None and owner != expected_owner):
            return False
        await self.send_text(owner, text, expected_generation=generation)
        if self.owner != owner or self._generation != generation:
            return False
        conversation = self._conversation("Reminders")
        self.runtime.store.add_message(conversation["id"], "assistant", text)
        return True
