"""Persistent reminders, a durable app notice feed, and best-effort notifications.

Due reminders and their notice/outbox entries are committed together. Telegram
deliveries are acknowledged after sending, so an ordinary restart never resends
an acknowledged notice. As Telegram has no idempotency key, a crash exactly
between a successful send and its acknowledgement can still duplicate it.
The newest 500 occurrences are retained; the app returns the newest 200.
Phone delivery retries expire after seven days or when an occurrence falls
outside that retention window, so an offline phone cannot grow storage forever.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import math
import os
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Any, Callable, TYPE_CHECKING

from jarvis.persona import format_now
from jarvis.storage import utc_now

if TYPE_CHECKING:
    from jarvis.runtime import Runtime

log = logging.getLogger("jarvis.reminders")
OUTBOX_KEY = "reminder_notices"
REPEATS = ("none", "daily", "weekdays", "weekly")
MAX_OUTBOX = 500
MAX_NOTICES = 200
PHONE_RETRY_DAYS = 7


def as_utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def next_occurrence(due: datetime, repeat: str, now: datetime) -> datetime:
    """Keep the local wall-clock time, skipping missed days and weekends."""
    local_due = due.astimezone().replace(tzinfo=None)
    local_now = now.astimezone().replace(tzinfo=None)
    days = max(0, (local_now.date() - local_due.date()).days)
    step = 7 if repeat == "weekly" else 1
    candidate = local_due + timedelta(days=(days // step) * step)
    while candidate.astimezone(timezone.utc) <= now.astimezone(timezone.utc) or (repeat == "weekdays" and candidate.weekday() >= 5):
        candidate += timedelta(days=step)
    return candidate.astimezone(timezone.utc)


def windows_toast(text: str) -> bool:
    """Ask Windows to show a toast; failure never prevents the in-app notice.

    Uses the built-in WinRT API, with XML escaped and passed as encoded data.
    https://learn.microsoft.com/en-us/uwp/api/windows.ui.notifications.toastnotificationmanager
    """
    if os.name != "nt":
        return False
    xml = '<toast><visual><binding template="ToastGeneric"><text>JARVIS</text><text>' + escape(text) + '</text></binding></visual></toast>'
    payload = base64.b64encode(xml.encode("utf-8")).decode("ascii")
    script = (
        "$ErrorActionPreference='Stop'\n"
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] > $null\n"
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType=WindowsRuntime] > $null\n"
        "$jarvisXml = New-Object Windows.Data.Xml.Dom.XmlDocument\n"
        f"$jarvisXml.LoadXml([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{payload}')))\n"
        "$jarvisToast = [Windows.UI.Notifications.ToastNotification]::new($jarvisXml)\n"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('JARVIS').Show($jarvisToast)\n"
    )
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-EncodedCommand",
             base64.b64encode(script.encode("utf-16-le")).decode("ascii")],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=8, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return completed.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


class ReminderService:
    def __init__(self, runtime: Runtime, *, toast: Callable[[str], bool] = windows_toast):
        self.runtime = runtime
        self.store = runtime.store
        self.toast = toast
        self._task: asyncio.Task | None = None
        self._tick_lock = asyncio.Lock()

    def create(
        self, text: str, *, at: str | None = None, in_minutes: float | None = None,
        repeat: str = "none", conversation_id: str | None = None, now: datetime | None = None,
    ) -> dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        if not isinstance(text, str) or not text.strip() or len(text.strip()) > 500:
            raise ValueError("Reminder text must contain 1–500 characters.")
        if repeat not in REPEATS:
            raise ValueError("Repeat must be none, daily, weekdays or weekly.")
        if (at is None) == (in_minutes is None):
            raise ValueError("Give either a local date and time or in_minutes, not both.")
        try:
            if in_minutes is not None:
                if (isinstance(in_minutes, bool) or not isinstance(in_minutes, (int, float))
                        or not 0 < in_minutes <= 525600 or not math.isfinite(in_minutes)):
                    raise ValueError("in_minutes must be between 0 and 525600, excluding 0.")
                due = now + timedelta(minutes=in_minutes)
            else:
                if not isinstance(at, str) or "T" not in at:
                    raise ValueError("Use a local ISO date and time, for example 2026-11-10T18:30.")
                due = parse_time(at).astimezone(timezone.utc)
            if due <= now:
                raise ValueError("The reminder time must be in the future.")
        except (TypeError, OverflowError) as exc:
            raise ValueError("That reminder date and time is invalid.") from exc
        with self.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT COUNT(*) FROM reminders WHERE status='pending'").fetchone()[0] >= 100:
                raise ValueError("There are already 100 pending reminders. Cancel one first.")
            cur = conn.execute(
                "INSERT INTO reminders (text, due_at, repeat, conversation_id, created_at) VALUES (?, ?, ?, ?, ?)",
                (text.strip(), as_utc(due), repeat, conversation_id, as_utc(now)),
            )
            row = conn.execute("SELECT * FROM reminders WHERE id=?", (cur.lastrowid,)).fetchone()
        return self._display(dict(row))

    @staticmethod
    def _display(reminder: dict[str, Any]) -> dict[str, Any]:
        return {**reminder, "due_local": format_now(parse_time(reminder["due_at"]).astimezone())}

    def list(self, status: str = "pending") -> list[dict[str, Any]]:
        if status not in ("pending", "sent", "cancelled", "all"):
            raise ValueError("Unknown reminder status.")
        with self.store._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM reminders " + ("" if status == "all" else "WHERE status=? ") + "ORDER BY due_at, id LIMIT 200",
                () if status == "all" else (status,),
            ).fetchall()
        return [self._display(dict(row)) for row in rows]

    def cancel(self, reminder_id: int) -> bool:
        with self.store._connect() as conn:
            changed = conn.execute("UPDATE reminders SET status='cancelled' WHERE id=? AND status='pending'", (reminder_id,))
        return changed.rowcount > 0

    @staticmethod
    def _state(conn: sqlite3.Connection) -> dict[str, Any]:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (OUTBOX_KEY,)).fetchone()
        return json.loads(row[0]) if row else {"seq": 0, "items": []}

    @staticmethod
    def _save_state(conn: sqlite3.Connection, state: dict[str, Any]) -> None:
        # Bound both completed and undelivered occurrences. Older phone retries expire.
        state["items"] = state["items"][-MAX_OUTBOX:]
        conn.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (OUTBOX_KEY, json.dumps(state), utc_now()),
        )

    def notices(self, after: int = 0) -> list[dict[str, Any]]:
        with self.store._connect() as conn:
            items = self._state(conn)["items"][-MAX_NOTICES:]
        return [{key: item[key] for key in ("seq", "reminder_id", "text", "message", "due_at", "created_at", "late")}
                for item in items if item["seq"] > after]

    def _ack(self, seq: int, field: str) -> None:
        with self.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            state = self._state(conn)
            for item in state["items"]:
                if item["seq"] == seq:
                    item[field] = False
            self._save_state(conn, state)

    async def tick(self, now: datetime | None = None) -> None:
        async with self._tick_lock:
            now = now or datetime.now(timezone.utc)
            telegram = getattr(self.runtime, "telegram", None)
            owner = telegram.owner if telegram else None
            with self.store._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                state = self._state(conn)
                due = conn.execute(
                    "SELECT * FROM reminders WHERE status='pending' AND due_at<=? ORDER BY due_at, id", (as_utc(now),)
                ).fetchall()
                for row in due:
                    reminder = dict(row)
                    due_at = parse_time(reminder["due_at"])
                    late = (now - due_at).total_seconds() > 60
                    state["seq"] += 1
                    message = f"Reminder #{reminder['id']}{' (late)' if late else ''}: {reminder['text']}"
                    state["items"].append({
                        "seq": state["seq"], "reminder_id": reminder["id"], "text": reminder["text"], "message": message,
                        "due_at": reminder["due_at"], "created_at": as_utc(now), "late": late,
                        "telegram_owner": owner, "telegram_pending": bool(owner), "toast_pending": True,
                    })
                    if reminder["repeat"] == "none":
                        conn.execute("UPDATE reminders SET status='sent', sent_at=? WHERE id=?", (as_utc(now), reminder["id"]))
                    else:
                        conn.execute("UPDATE reminders SET due_at=?, sent_at=? WHERE id=?", (
                            as_utc(next_occurrence(due_at, reminder["repeat"], now)), as_utc(now), reminder["id"],
                        ))
                self._save_state(conn, state)
            for item in state["items"]:
                if item["telegram_pending"]:
                    current_owner = telegram.owner if telegram else None
                    expired = now - parse_time(item["created_at"]) >= timedelta(days=PHONE_RETRY_DAYS)
                    if not current_owner or item["telegram_owner"] != current_owner or expired:
                        self._ack(item["seq"], "telegram_pending")
                    else:
                        try:
                            if await telegram.send_reminder(item["message"], expected_owner=item["telegram_owner"]):
                                self._ack(item["seq"], "telegram_pending")
                        except Exception:
                            log.warning("Phone reminder delivery failed; it will retry.")
                if item["toast_pending"]:
                    # Toasts are best effort, and do not repeat after restart.
                    self._ack(item["seq"], "toast_pending")
                    try:
                        await asyncio.to_thread(self.toast, item["message"])
                    except Exception:
                        log.warning("Windows reminder notification was unavailable.")

    async def _run(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                log.exception("Reminder scheduler failed; it will retry.")
            await asyncio.sleep(15)

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
