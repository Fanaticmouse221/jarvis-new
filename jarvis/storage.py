"""Persistent storage (SQLite): conversations, long-term memory, settings, action log, usage.

SQLite needs no server and keeps everything in one file (default
`data/jarvis.db`), which is easy to back up. A new connection is opened per
operation, which is simple and thread-safe for a single-user app.

Schema changes are numbered migrations tracked with `PRAGMA user_version`, so
existing databases upgrade in place. Full-text search (FTS5) indexes memories
and messages; if this SQLite build lacks FTS5, search falls back to LIKE.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

MEMORY_KINDS = ("style", "preference", "personal", "project", "note")

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
    # v2: agent steps per message, rolling summaries, memory, settings, action log, usage
    """
    ALTER TABLE messages ADD COLUMN parts TEXT;
    ALTER TABLE conversations ADD COLUMN summary TEXT;
    ALTER TABLE conversations ADD COLUMN summary_upto INTEGER NOT NULL DEFAULT 0;
    CREATE TABLE memories (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        kind             TEXT NOT NULL DEFAULT 'note',
        content          TEXT NOT NULL,
        pinned           INTEGER NOT NULL DEFAULT 0,
        source           TEXT NOT NULL DEFAULT 'told',
        conversation_id  TEXT,
        created_at       TEXT NOT NULL,
        updated_at       TEXT NOT NULL,
        last_used_at     TEXT,
        use_count        INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE settings (
        key         TEXT PRIMARY KEY,
        value       TEXT NOT NULL,
        updated_at  TEXT NOT NULL
    );
    CREATE TABLE tool_runs (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id           TEXT NOT NULL,
        conversation_id  TEXT,
        tool             TEXT NOT NULL,
        title            TEXT NOT NULL,
        args             TEXT NOT NULL,
        risk             TEXT NOT NULL,
        decision         TEXT NOT NULL,
        status           TEXT NOT NULL,
        summary          TEXT,
        started_at       TEXT NOT NULL,
        duration_ms      INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX idx_tool_runs_started ON tool_runs(id DESC);
    CREATE TABLE usage (
        day                TEXT NOT NULL,
        model              TEXT NOT NULL,
        requests           INTEGER NOT NULL DEFAULT 0,
        prompt_tokens      INTEGER NOT NULL DEFAULT 0,
        completion_tokens  INTEGER NOT NULL DEFAULT 0,
        errors             INTEGER NOT NULL DEFAULT 0,
        rate_limited       INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (day, model)
    );
    """,
]

FTS_SETUP = """
CREATE VIRTUAL TABLE IF NOT EXISTS {t}_fts USING fts5(content, content='{t}', content_rowid='id', tokenize='porter unicode61');
CREATE TRIGGER IF NOT EXISTS {t}_fts_ai AFTER INSERT ON {t} BEGIN
    INSERT INTO {t}_fts(rowid, content) VALUES (new.id, new.content);
END;
CREATE TRIGGER IF NOT EXISTS {t}_fts_ad AFTER DELETE ON {t} BEGIN
    INSERT INTO {t}_fts({t}_fts, rowid, content) VALUES ('delete', old.id, old.content);
END;
CREATE TRIGGER IF NOT EXISTS {t}_fts_au AFTER UPDATE OF content ON {t} BEGIN
    INSERT INTO {t}_fts({t}_fts, rowid, content) VALUES ('delete', old.id, old.content);
    INSERT INTO {t}_fts(rowid, content) VALUES (new.id, new.content);
END;
"""

STOPWORDS = frozenset(
    "a an and are as at be but by can could did do does for from had has have he her his how i if in "
    "into is it its just me my of on or our out she so some than that the their them then there these "
    "they this to up us was we were what when where which who why will with would you your about tell "
    "please know remember".split()
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def local_day() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def keywords(text: str, limit: int = 12) -> list[str]:
    """Distinct meaningful words from free text, for building a search query."""
    seen: list[str] = []
    for word in re.findall(r"[A-Za-z0-9][A-Za-z0-9']+", text.lower()):
        word = word.strip("'")
        if len(word) > 1 and word not in STOPWORDS and word not in seen:
            seen.append(word)
        if len(seen) >= limit:
            break
    return seen


def fts_query(text: str) -> str | None:
    """An FTS5 query that matches any keyword (as a prefix). None if there are no keywords."""
    words = [re.sub(r"[^a-z0-9]", "", word) for word in keywords(text)]
    words = [word for word in words if word]
    return " OR ".join(f'"{word}"*' for word in words) if words else None


class Store:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fts = False
        self._migrate()
        self._ensure_fts()

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

    def _ensure_fts(self) -> None:
        try:
            with self._connect() as conn:
                existing = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE name IN ('memories_fts', 'messages_fts')"
                    )
                }
                for table in ("memories", "messages"):
                    conn.executescript(FTS_SETUP.format(t=table))
                    if f"{table}_fts" not in existing:
                        conn.execute(f"INSERT INTO {table}_fts({table}_fts) VALUES ('rebuild')")
            self.fts = True
        except sqlite3.OperationalError:
            self.fts = False

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

    def list_conversations(self, limit: int = 200, query: str = "") -> list[dict[str, Any]]:
        sql = (
            "SELECT c.id, c.title, c.created_at, c.updated_at, "
            "       (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS message_count "
            "FROM conversations c {where} ORDER BY c.updated_at DESC, c.rowid DESC LIMIT ?"
        )
        with self._connect() as conn:
            if not query.strip():
                rows = conn.execute(sql.format(where=""), (limit,)).fetchall()
            else:
                ids = {hit["conversation_id"] for hit in self._search_messages(conn, query, 200)}
                like = f"%{query.strip()}%"
                ids |= {row[0] for row in conn.execute("SELECT id FROM conversations WHERE title LIKE ?", (like,))}
                if not ids:
                    return []
                marks = ",".join("?" * len(ids))
                rows = conn.execute(sql.format(where=f"WHERE c.id IN ({marks})"), (*ids, limit)).fetchall()
        return [dict(row) for row in rows]

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, title, created_at, updated_at, summary, summary_upto FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
        return dict(row) if row else None

    def rename_conversation(self, conversation_id: str, title: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("UPDATE conversations SET title = ? WHERE id = ?", (title, conversation_id))
        return cur.rowcount > 0

    def set_summary(self, conversation_id: str, summary: str, upto: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE conversations SET summary = ?, summary_upto = ? WHERE id = ?",
                (summary, upto, conversation_id),
            )

    def delete_conversation(self, conversation_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        return cur.rowcount > 0

    def delete_all_conversations(self) -> int:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM conversations")
        return cur.rowcount

    # ----- messages ------------------------------------------------------

    @staticmethod
    def _message(row: sqlite3.Row) -> dict[str, Any]:
        message = dict(row)
        message["parts"] = json.loads(message["parts"]) if message.get("parts") else None
        return message

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        model: str | None = None,
        parts: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO messages (conversation_id, role, content, model, parts, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (conversation_id, role, content, model, json.dumps(parts) if parts else None, now),
            )
            conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))
        return {
            "id": cur.lastrowid,
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
            "model": model,
            "parts": parts,
            "created_at": now,
        }

    def get_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, conversation_id, role, content, model, parts, created_at "
                "FROM messages WHERE conversation_id = ? ORDER BY id",
                (conversation_id,),
            ).fetchall()
        return [self._message(row) for row in rows]

    def delete_messages_from(self, conversation_id: str, message_id: int) -> int:
        """Delete a message and everything after it (used by regenerate and edit)."""
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM messages WHERE conversation_id = ? AND id >= ?", (conversation_id, message_id)
            )
            conn.execute(
                "UPDATE conversations SET summary = NULL, summary_upto = 0 "
                "WHERE id = ? AND summary_upto >= ?",
                (conversation_id, message_id),
            )
        return cur.rowcount

    def _search_messages(self, conn: sqlite3.Connection, query: str, limit: int) -> list[dict[str, Any]]:
        match = fts_query(query) if self.fts else None
        if match:
            rows = conn.execute(
                "SELECT m.id, m.conversation_id, m.role, m.created_at, c.title, "
                "       snippet(messages_fts, 0, '', '', ' … ', 28) AS snippet "
                "FROM messages_fts JOIN messages m ON m.id = messages_fts.rowid "
                "JOIN conversations c ON c.id = m.conversation_id "
                "WHERE messages_fts MATCH ? ORDER BY bm25(messages_fts) LIMIT ?",
                (match, limit),
            ).fetchall()
        else:
            words = keywords(query) or [query.strip().lower()]
            where = " OR ".join("lower(m.content) LIKE ?" for _ in words)
            rows = conn.execute(
                "SELECT m.id, m.conversation_id, m.role, m.created_at, c.title, substr(m.content, 1, 220) AS snippet "
                f"FROM messages m JOIN conversations c ON c.id = m.conversation_id WHERE {where} "
                "ORDER BY m.id DESC LIMIT ?",
                (*[f"%{word}%" for word in words], limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def search_messages(self, query: str, limit: int = 6, exclude_conversation: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            hits = self._search_messages(conn, query, limit + 20)
        if exclude_conversation:
            hits = [hit for hit in hits if hit["conversation_id"] != exclude_conversation]
        return hits[:limit]

    # ----- long-term memory ----------------------------------------------

    @staticmethod
    def _memory(row: sqlite3.Row) -> dict[str, Any]:
        memory = dict(row)
        memory["pinned"] = bool(memory["pinned"])
        memory.pop("score", None)
        return memory

    def add_memory(
        self, content: str, kind: str = "note", source: str = "told", conversation_id: str | None = None
    ) -> dict[str, Any]:
        now = utc_now()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO memories (kind, content, source, conversation_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (kind, content, source, conversation_id, now, now),
            )
        return self.get_memory(cur.lastrowid)  # type: ignore[return-value]

    def get_memory(self, memory_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        return self._memory(row) if row else None

    def update_memory(self, memory_id: int, **fields: Any) -> dict[str, Any] | None:
        allowed = {key: value for key, value in fields.items() if key in ("content", "kind", "pinned") and value is not None}
        if "pinned" in allowed:
            allowed["pinned"] = 1 if allowed["pinned"] else 0
        if allowed:
            sets = ", ".join(f"{key} = ?" for key in allowed)
            with self._connect() as conn:
                conn.execute(
                    f"UPDATE memories SET {sets}, updated_at = ? WHERE id = ?",
                    (*allowed.values(), utc_now(), memory_id),
                )
        return self.get_memory(memory_id)

    def delete_memory(self, memory_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        return cur.rowcount > 0

    def delete_all_memories(self) -> int:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM memories")
        return cur.rowcount

    def list_memories(self, kind: str | None = None, after_id: int = 0) -> list[dict[str, Any]]:
        sql = "SELECT * FROM memories WHERE id > ?"
        params: list[Any] = [after_id]
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        with self._connect() as conn:
            rows = conn.execute(sql + " ORDER BY pinned DESC, updated_at DESC, id DESC", params).fetchall()
        return [self._memory(row) for row in rows]

    def search_memories(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        match = fts_query(query) if self.fts else None
        with self._connect() as conn:
            if match:
                rows = conn.execute(
                    "SELECT m.*, bm25(memories_fts) AS score FROM memories_fts "
                    "JOIN memories m ON m.id = memories_fts.rowid "
                    "WHERE memories_fts MATCH ? ORDER BY score LIMIT ?",
                    (match, limit),
                ).fetchall()
            else:
                words = keywords(query) or [query.strip().lower()]
                where = " OR ".join("lower(content) LIKE ?" for _ in words)
                rows = conn.execute(
                    f"SELECT * FROM memories WHERE {where} ORDER BY updated_at DESC LIMIT ?",
                    (*[f"%{word}%" for word in words], limit),
                ).fetchall()
        return [self._memory(row) for row in rows]

    def touch_memories(self, ids: list[int]) -> None:
        if not ids:
            return
        marks = ",".join("?" * len(ids))
        with self._connect() as conn:
            conn.execute(
                f"UPDATE memories SET use_count = use_count + 1, last_used_at = ? WHERE id IN ({marks})",
                (utc_now(), *ids),
            )

    # ----- settings ------------------------------------------------------

    def get_settings(self) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
        return {row["key"]: json.loads(row["value"]) for row in rows}

    def get_setting(self, key: str, default: Any = None) -> Any:
        return self.get_settings().get(key, default)

    def set_setting(self, key: str, value: Any) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                (key, json.dumps(value), utc_now()),
            )

    # ----- action log ----------------------------------------------------

    def add_tool_run(
        self,
        *,
        run_id: str,
        conversation_id: str | None,
        tool: str,
        title: str,
        args: dict[str, Any],
        risk: str,
        decision: str,
        status: str,
        summary: str,
        duration_ms: int = 0,
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO tool_runs (run_id, conversation_id, tool, title, args, risk, decision, status, "
                "summary, started_at, duration_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    conversation_id,
                    tool,
                    title,
                    json.dumps(args, ensure_ascii=False)[:2000],
                    risk,
                    decision,
                    status,
                    summary[:500],
                    utc_now(),
                    duration_ms,
                ),
            )
        return int(cur.lastrowid or 0)

    def list_tool_runs(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT t.*, c.title AS conversation_title FROM tool_runs t "
                "LEFT JOIN conversations c ON c.id = t.conversation_id ORDER BY t.id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        runs = [dict(row) for row in rows]
        for run in runs:
            run["args"] = json.loads(run["args"]) if run["args"].startswith("{") and run["args"].endswith("}") else {}
        return runs

    # ----- usage ---------------------------------------------------------

    def record_usage(
        self,
        model: str,
        *,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        error: bool = False,
        rate_limited: bool = False,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO usage (day, model, requests, prompt_tokens, completion_tokens, errors, rate_limited) "
                "VALUES (?, ?, 1, ?, ?, ?, ?) ON CONFLICT(day, model) DO UPDATE SET "
                "requests = requests + 1, prompt_tokens = prompt_tokens + excluded.prompt_tokens, "
                "completion_tokens = completion_tokens + excluded.completion_tokens, "
                "errors = errors + excluded.errors, rate_limited = rate_limited + excluded.rate_limited",
                (local_day(), model, prompt_tokens, completion_tokens, int(error), int(rate_limited)),
            )

    def usage_for_day(self, day: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM usage WHERE day = ? ORDER BY requests DESC", (day or local_day(),)
            ).fetchall()
        return [dict(row) for row in rows]

    def requests_today(self) -> int:
        return sum(row["requests"] for row in self.usage_for_day())

    def counts(self) -> dict[str, int]:
        with self._connect() as conn:
            return {
                table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("conversations", "messages", "memories", "tool_runs")
            }
