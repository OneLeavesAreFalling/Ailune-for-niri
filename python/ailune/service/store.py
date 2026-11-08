"""SQLite persistence for characters, providers, conversations and memories.

Each operation opens a short-lived connection, which keeps the service safe
under FastAPI's thread pool without sharing sqlite3 objects across threads.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA_VERSION = 1

DEFAULT_PERSONALITY_ID = "pers_ailune_default"
DEFAULT_PERSONALITY_PROMPT = (
    "You are Ailune, a warm, curious and slightly playful AI companion who lives on the "
    "user's Linux desktop. Be natural and concise. Remember that you are a companion, not "
    "an assistant reading from a manual: react to the user's mood, ask small follow-up "
    "questions when appropriate, and avoid repeating the same phrases. Never claim to have "
    "done things on the computer that you cannot actually do. You may use emoji sparingly."
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS personalities (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    system_prompt TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS characters (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    model_path TEXT NOT NULL,
    model_entry TEXT NOT NULL,
    personality_id TEXT REFERENCES personalities(id) ON DELETE SET NULL,
    reply_language TEXT NOT NULL DEFAULT 'auto',
    scale REAL NOT NULL DEFAULT 1.0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS providers (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    provider_type TEXT NOT NULL,
    base_url TEXT NOT NULL,
    model_name TEXT NOT NULL,
    temperature REAL NOT NULL DEFAULT 0.8,
    max_tokens INTEGER,
    timeout_seconds REAL NOT NULL DEFAULT 60,
    extra_params TEXT NOT NULL DEFAULT '{}',
    secret_ref TEXT NOT NULL,
    is_default INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    character_id TEXT NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    title TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('system', 'user', 'assistant')),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    character_id TEXT NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_characters_personality ON characters(personality_id);
CREATE INDEX IF NOT EXISTS idx_conversations_character ON conversations(character_id);
CREATE INDEX IF NOT EXISTS idx_conversations_updated ON conversations(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_memories_character ON memories(character_id);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(SCHEMA)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            count = conn.execute("SELECT COUNT(*) FROM personalities").fetchone()[0]
            if count == 0:
                ts = now_iso()
                conn.execute(
                    "INSERT INTO personalities (id, name, system_prompt, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (DEFAULT_PERSONALITY_ID, "Ailune", DEFAULT_PERSONALITY_PROMPT, ts, ts),
                )
        try:
            import os

            os.chmod(self.path, 0o600)
        except OSError:
            pass

    @staticmethod
    def _dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    # ------------------------------------------------------------------ personalities

    def list_personalities(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM personalities ORDER BY created_at ASC").fetchall()
        return [dict(r) for r in rows]

    def get_personality(self, personality_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM personalities WHERE id = ?", (personality_id,)).fetchone()
        return self._dict(row)

    def create_personality(self, name: str, system_prompt: str) -> dict[str, Any]:
        personality_id = new_id("pers")
        ts = now_iso()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO personalities (id, name, system_prompt, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (personality_id, name, system_prompt, ts, ts),
            )
        return self.get_personality(personality_id) or {}

    def update_personality(self, personality_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        allowed = {k: v for k, v in fields.items() if k in {"name", "system_prompt"}}
        if not allowed:
            return self.get_personality(personality_id)
        allowed["updated_at"] = now_iso()
        assignments = ", ".join(f"{key} = ?" for key in allowed)
        values = [*allowed.values(), personality_id]
        with self._connect() as conn:
            cur = conn.execute(f"UPDATE personalities SET {assignments} WHERE id = ?", values)
        if cur.rowcount == 0:
            return None
        return self.get_personality(personality_id)

    def delete_personality(self, personality_id: str) -> bool:
        if personality_id == DEFAULT_PERSONALITY_ID:
            return False
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM personalities WHERE id = ?", (personality_id,))
        return cur.rowcount > 0

    # ------------------------------------------------------------------ characters

    def list_characters(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM characters ORDER BY created_at ASC").fetchall()
        return [dict(r) for r in rows]

    def get_character(self, character_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM characters WHERE id = ?", (character_id,)).fetchone()
        return self._dict(row)

    def create_character(self, data: dict[str, Any]) -> dict[str, Any]:
        character_id = new_id("char")
        ts = now_iso()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO characters (id, name, model_path, model_entry, personality_id, "
                "reply_language, scale, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    character_id,
                    data["name"],
                    data["model_path"],
                    data["model_entry"],
                    data.get("personality_id"),
                    data.get("reply_language", "auto"),
                    float(data.get("scale", 1.0)),
                    ts,
                    ts,
                ),
            )
        return self.get_character(character_id) or {}

    def update_character(self, character_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        allowed_keys = {"name", "model_path", "model_entry", "personality_id", "reply_language", "scale"}
        allowed = {k: v for k, v in fields.items() if k in allowed_keys}
        if not allowed:
            return self.get_character(character_id)
        allowed["updated_at"] = now_iso()
        assignments = ", ".join(f"{key} = ?" for key in allowed)
        values = [*allowed.values(), character_id]
        with self._connect() as conn:
            cur = conn.execute(f"UPDATE characters SET {assignments} WHERE id = ?", values)
        if cur.rowcount == 0:
            return None
        return self.get_character(character_id)

    def delete_character(self, character_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM characters WHERE id = ?", (character_id,))
        return cur.rowcount > 0

    # ------------------------------------------------------------------ providers

    @staticmethod
    def _provider_row(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        try:
            value["extra_params"] = json.loads(value.get("extra_params") or "{}")
        except json.JSONDecodeError:
            value["extra_params"] = {}
        value["is_default"] = bool(value.get("is_default"))
        return value

    def list_providers(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM providers ORDER BY is_default DESC, created_at ASC"
            ).fetchall()
        return [self._provider_row(r) for r in rows]

    def get_provider(self, provider_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM providers WHERE id = ?", (provider_id,)).fetchone()
        return self._provider_row(row) if row is not None else None

    def get_default_provider(self) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM providers ORDER BY is_default DESC, created_at ASC LIMIT 1"
            ).fetchone()
        return self._provider_row(row) if row is not None else None

    def count_providers(self) -> int:
        with self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM providers").fetchone()[0])

    def create_provider(
        self, data: dict[str, Any], secret_ref: str, provider_id: str | None = None
    ) -> dict[str, Any]:
        provider_id = provider_id or new_id("prov")
        ts = now_iso()
        first = self.count_providers() == 0
        is_default = bool(data.get("is_default")) or first
        with self._connect() as conn:
            if is_default:
                conn.execute("UPDATE providers SET is_default = 0")
            conn.execute(
                "INSERT INTO providers (id, display_name, provider_type, base_url, model_name, "
                "temperature, max_tokens, timeout_seconds, extra_params, secret_ref, is_default, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    provider_id,
                    data["display_name"],
                    data["provider_type"],
                    data["base_url"],
                    data["model_name"],
                    float(data.get("temperature", 0.8)),
                    data.get("max_tokens"),
                    float(data.get("timeout_seconds", 60)),
                    json.dumps(data.get("extra_params") or {}, ensure_ascii=False),
                    secret_ref,
                    1 if is_default else 0,
                    ts,
                    ts,
                ),
            )
        return self.get_provider(provider_id) or {}

    def update_provider(self, provider_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        allowed_keys = {
            "display_name",
            "provider_type",
            "base_url",
            "model_name",
            "temperature",
            "max_tokens",
            "timeout_seconds",
            "extra_params",
            "is_default",
        }
        payload = {k: v for k, v in fields.items() if k in allowed_keys}
        if not payload:
            return self.get_provider(provider_id)
        if "extra_params" in payload:
            payload["extra_params"] = json.dumps(payload["extra_params"] or {}, ensure_ascii=False)
        if "is_default" in payload:
            payload["is_default"] = 1 if payload["is_default"] else 0
        payload["updated_at"] = now_iso()
        assignments = ", ".join(f"{key} = ?" for key in payload)
        values = [*payload.values(), provider_id]
        with self._connect() as conn:
            if payload.get("is_default"):
                conn.execute("UPDATE providers SET is_default = 0")
            cur = conn.execute(f"UPDATE providers SET {assignments} WHERE id = ?", values)
        if cur.rowcount == 0:
            return None
        return self.get_provider(provider_id)

    def delete_provider(self, provider_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT is_default FROM providers WHERE id = ?", (provider_id,)).fetchone()
            if row is None:
                return False
            conn.execute("DELETE FROM providers WHERE id = ?", (provider_id,))
            if row["is_default"]:
                conn.execute(
                    "UPDATE providers SET is_default = 1 WHERE id = "
                    "(SELECT id FROM providers ORDER BY created_at ASC LIMIT 1)"
                )
        return True

    # ------------------------------------------------------------------ conversations

    def create_conversation(self, character_id: str, title: str | None = None) -> dict[str, Any]:
        conversation_id = new_id("conv")
        ts = now_iso()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO conversations (id, character_id, title, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (conversation_id, character_id, title, ts, ts),
            )
        return self.get_conversation(conversation_id) or {}

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
        return self._dict(row)

    def list_conversations(self, character_id: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if character_id:
                rows = conn.execute(
                    "SELECT * FROM conversations WHERE character_id = ? ORDER BY updated_at DESC",
                    (character_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM conversations ORDER BY updated_at DESC"
                ).fetchall()
        return [dict(r) for r in rows]

    def delete_conversation(self, conversation_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        return cur.rowcount > 0

    def add_message(self, conversation_id: str, role: str, content: str) -> dict[str, Any]:
        message_id = new_id("msg")
        ts = now_iso()
        with self._connect() as conn:
            conversation = conn.execute(
                "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
            if conversation is None:
                raise KeyError("conversation not found")
            conn.execute(
                "INSERT INTO messages (id, conversation_id, role, content, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (message_id, conversation_id, role, content, ts),
            )
            title = conversation["title"]
            if role == "user" and not title:
                title = content.strip().replace("\n", " ")[:60]
                if len(content.strip()) > 60:
                    title += "…"
            conn.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                (title, ts, conversation_id),
            )
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
        return dict(row)

    def list_messages(self, conversation_id: str, limit: int = 200) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 1000))
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE conversation_id = ? ORDER BY rowid ASC LIMIT ?",
                (conversation_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def recent_messages(self, conversation_id: str, limit: int = 24) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 100))
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE conversation_id = ? ORDER BY rowid DESC LIMIT ?",
                (conversation_id, limit),
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    # ------------------------------------------------------------------ memories

    def list_memories(self, character_id: str, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM memories WHERE character_id = ? ORDER BY rowid DESC LIMIT ?",
                (character_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def add_memory(self, character_id: str, content: str) -> dict[str, Any]:
        memory_id = new_id("mem")
        ts = now_iso()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO memories (id, character_id, content, created_at) VALUES (?, ?, ?, ?)",
                (memory_id, character_id, content, ts),
            )
            row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        return dict(row)

    def delete_memory(self, memory_id: str, character_id: str | None = None) -> bool:
        with self._connect() as conn:
            if character_id:
                cur = conn.execute(
                    "DELETE FROM memories WHERE id = ? AND character_id = ?",
                    (memory_id, character_id),
                )
            else:
                cur = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        return cur.rowcount > 0

    # ------------------------------------------------------------------ stats

    def stats(self) -> dict[str, int]:
        with self._connect() as conn:
            tables = ("characters", "personalities", "providers", "conversations", "messages", "memories")
            result = {}
            for table in tables:
                result[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        return result
