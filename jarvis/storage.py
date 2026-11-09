"""Persistent conversation storage (SQLite).

SQLite needs no server and keeps everything in one file (default
`data/jarvis.db`), which is easy to back up. A new connection is opened per
operation, which is simple and thread-safe for a single-user app.

Schema changes are applied as numbered migrations tracked with
`PRAGMA user_version`, so existing databases upgrade in place.
"""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

MIGRATIONS: list[str] = [
    # v1: conversations and messages
    """
    CREATE TABLE conversations (
        id          TEXT PRIMARY KEY,
        title       TEXT NOT NULL,
        created_at  TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    );
    CREATE TABLE messages (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id  TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
        role             TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
        content          TEXT NOT NULL,
        model            TEXT,
        created_at       TEXT NOT NULL
    );
    CREATE INDEX idx_messages_conversation ON messages(conversation_id, id);
    CREATE INDEX idx_conversations_updated ON conversations(updated_at);
    """,
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Store:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _migrate(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            for index in range(version, len(MIGRATIONS)):
                conn.executescript(MIGRATIONS[index])
                conn.execute(f"PRAGMA user_version = {index + 1}")

    # ----- conversations -------------------------------------------------

    def create_conversation(self, title: str = "New conversation") -> dict[str, Any]:
        now = utc_now()
        conv = {"id": uuid.uuid4().hex, "title": title, "created_at": now, "updated_at": now}
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO conversations (id, title, created_at, updated_at) "
                "VALUES (:id, :title, :created_at, :updated_at)",
                conv,
            )
        return conv

    def list_conversations(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT c.id, c.title, c.created_at, c.updated_at, "
                "       (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS message_count "
                "FROM conversations c ORDER BY c.updated_at DESC, c.rowid DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, title, created_at, updated_at FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
        return dict(row) if row else None

    def rename_conversation(self, conversation_id: str, title: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE conversations SET title = ? WHERE id = ?", (title, conversation_id)
            )
        return cur.rowcount > 0

    def delete_conversation(self, conversation_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        return cur.rowcount > 0

    # ----- messages ------------------------------------------------------

    def add_message(
        self, conversation_id: str, role: str, content: str, model: str | None = None
    ) -> dict[str, Any]:
        now = utc_now()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO messages (conversation_id, role, content, model, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (conversation_id, role, content, model, now),
            )
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id)
            )
        return {
            "id": cur.lastrowid,
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
            "model": model,
            "created_at": now,
        }

    def get_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, conversation_id, role, content, model, created_at "
                "FROM messages WHERE conversation_id = ? ORDER BY id",
                (conversation_id,),
            ).fetchall()
        return [dict(row) for row in rows]
