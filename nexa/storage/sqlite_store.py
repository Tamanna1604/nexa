"""SQLite implementation of :class:`StructuredStore`.

One connection is opened per call (like the original `memory.py`). That keeps
things thread-safe for the API without a connection pool, and a personal
assistant's write volume is tiny.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Sequence

from nexa.models import Chunk, ChatMessage, Document, Memory
from nexa.storage.base import StructuredStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


class SQLiteStore(StructuredStore):
    def __init__(self, path: str) -> None:
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # ------------------------------------------------------------------
    # schema / migration
    # ------------------------------------------------------------------
    def setup(self) -> None:
        conn = self._connect()
        cur = conn.cursor()

        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id         TEXT PRIMARY KEY,
                title      TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id              TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                role            TEXT NOT NULL,
                content         TEXT NOT NULL,
                created_at      TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, created_at);

            CREATE TABLE IF NOT EXISTS memories (
                id         TEXT PRIMARY KEY,
                text       TEXT NOT NULL,
                memory_type TEXT,
                importance INTEGER,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS documents (
                id         TEXT PRIMARY KEY,
                path       TEXT NOT NULL,
                title      TEXT,
                hash       TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS chunks (
                id          TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                ordinal     INTEGER NOT NULL,
                text        TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(document_id, ordinal);
            """
        )

        # Migrate an older `memories` table (from Nexa v1) to the new columns.
        existing = {row["name"] for row in cur.execute("PRAGMA table_info(memories)")}
        for column, ddl in (
            ("source_message_id", "ALTER TABLE memories ADD COLUMN source_message_id TEXT"),
            ("last_used_at", "ALTER TABLE memories ADD COLUMN last_used_at TEXT"),
            ("use_count", "ALTER TABLE memories ADD COLUMN use_count INTEGER DEFAULT 0"),
        ):
            if column not in existing:
                cur.execute(ddl)

        conn.commit()
        conn.close()

    # ------------------------------------------------------------------
    # conversations & messages
    # ------------------------------------------------------------------
    def create_conversation(self, title: str = "") -> str:
        conv_id = _uuid()
        conn = self._connect()
        conn.execute(
            "INSERT INTO conversations (id, title, created_at) VALUES (?, ?, ?)",
            (conv_id, title, _now()),
        )
        conn.commit()
        conn.close()
        return conv_id

    def conversation_exists(self, conversation_id: str) -> bool:
        conn = self._connect()
        row = conn.execute(
            "SELECT 1 FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        conn.close()
        return row is not None

    def add_message(self, conversation_id: str, role: str, content: str) -> ChatMessage:
        msg = ChatMessage(_uuid(), conversation_id, role, content, _now())
        conn = self._connect()
        conn.execute(
            "INSERT INTO messages (id, conversation_id, role, content, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (msg.id, msg.conversation_id, msg.role, msg.content, msg.created_at),
        )
        conn.commit()
        conn.close()
        return msg

    def recent_messages(self, conversation_id: str, limit: int) -> list[ChatMessage]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT * FROM messages WHERE conversation_id = ? "
            "ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (conversation_id, limit),
        ).fetchall()
        conn.close()
        return [self._row_to_message(r) for r in reversed(rows)]

    def all_messages(self, conversation_id: str) -> list[ChatMessage]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC, rowid ASC",
            (conversation_id,),
        ).fetchall()
        conn.close()
        return [self._row_to_message(r) for r in rows]

    @staticmethod
    def _row_to_message(r: sqlite3.Row) -> ChatMessage:
        return ChatMessage(r["id"], r["conversation_id"], r["role"], r["content"], r["created_at"])

    # ------------------------------------------------------------------
    # long-term memories
    # ------------------------------------------------------------------
    def add_memory(self, memory: Memory) -> None:
        conn = self._connect()
        conn.execute(
            "INSERT INTO memories "
            "(id, text, memory_type, importance, created_at, source_message_id, last_used_at, use_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                memory.id,
                memory.text,
                memory.memory_type,
                memory.importance,
                memory.created_at,
                None,
                memory.last_used_at,
                memory.use_count,
            ),
        )
        conn.commit()
        conn.close()

    def all_memories(self) -> list[Memory]:
        conn = self._connect()
        rows = conn.execute("SELECT * FROM memories").fetchall()
        conn.close()
        return [self._row_to_memory(r) for r in rows]

    def get_memory(self, memory_id: str) -> Memory | None:
        conn = self._connect()
        row = conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        conn.close()
        return self._row_to_memory(row) if row else None

    def delete_memory(self, memory_id: str) -> None:
        conn = self._connect()
        conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        conn.commit()
        conn.close()

    def touch_memory(self, memory_id: str, used_at: str) -> None:
        conn = self._connect()
        conn.execute(
            "UPDATE memories SET use_count = COALESCE(use_count, 0) + 1, last_used_at = ? WHERE id = ?",
            (used_at, memory_id),
        )
        conn.commit()
        conn.close()

    @staticmethod
    def _row_to_memory(r: sqlite3.Row) -> Memory:
        keys = r.keys()
        return Memory(
            id=r["id"],
            text=r["text"],
            memory_type=r["memory_type"] or "general",
            importance=r["importance"] or 5,
            created_at=r["created_at"] or "",
            last_used_at=r["last_used_at"] if "last_used_at" in keys else None,
            use_count=(r["use_count"] if "use_count" in keys else 0) or 0,
        )

    # ------------------------------------------------------------------
    # RAG documents & chunks
    # ------------------------------------------------------------------
    def get_document_by_hash(self, content_hash: str) -> Document | None:
        return self._get_document("hash", content_hash)

    def get_document_by_path(self, path: str) -> Document | None:
        return self._get_document("path", path)

    def _get_document(self, column: str, value: str) -> Document | None:
        conn = self._connect()
        row = conn.execute(
            f"SELECT * FROM documents WHERE {column} = ?", (value,)
        ).fetchone()
        conn.close()
        if row is None:
            return None
        return Document(row["id"], row["path"], row["title"] or "", row["hash"], row["created_at"])

    def add_document(self, document: Document) -> None:
        conn = self._connect()
        conn.execute(
            "INSERT INTO documents (id, path, title, hash, created_at) VALUES (?, ?, ?, ?, ?)",
            (document.id, document.path, document.title, document.hash, document.created_at),
        )
        conn.commit()
        conn.close()

    def delete_document(self, document_id: str) -> list[str]:
        conn = self._connect()
        chunk_ids = [
            r["id"]
            for r in conn.execute(
                "SELECT id FROM chunks WHERE document_id = ?", (document_id,)
            ).fetchall()
        ]
        conn.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
        conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        conn.commit()
        conn.close()
        return chunk_ids

    def add_chunks(self, chunks: Sequence[Chunk]) -> None:
        conn = self._connect()
        conn.executemany(
            "INSERT INTO chunks (id, document_id, ordinal, text, created_at) VALUES (?, ?, ?, ?, ?)",
            [(c.id, c.document_id, c.ordinal, c.text, _now()) for c in chunks],
        )
        conn.commit()
        conn.close()

    def all_chunks(self) -> list[Chunk]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT c.*, d.title AS doc_title FROM chunks c "
            "LEFT JOIN documents d ON d.id = c.document_id ORDER BY c.document_id, c.ordinal"
        ).fetchall()
        conn.close()
        return [self._row_to_chunk(r) for r in rows]

    def get_chunks(self, chunk_ids: Sequence[str]) -> list[Chunk]:
        if not chunk_ids:
            return []
        placeholders = ",".join("?" for _ in chunk_ids)
        conn = self._connect()
        rows = conn.execute(
            f"SELECT c.*, d.title AS doc_title FROM chunks c "
            f"LEFT JOIN documents d ON d.id = c.document_id WHERE c.id IN ({placeholders})",
            tuple(chunk_ids),
        ).fetchall()
        conn.close()
        by_id = {r["id"]: self._row_to_chunk(r) for r in rows}
        return [by_id[cid] for cid in chunk_ids if cid in by_id]

    def list_documents(self) -> list[Document]:
        conn = self._connect()
        rows = conn.execute("SELECT * FROM documents ORDER BY created_at DESC").fetchall()
        conn.close()
        return [
            Document(r["id"], r["path"], r["title"] or "", r["hash"], r["created_at"])
            for r in rows
        ]

    @staticmethod
    def _row_to_chunk(r: sqlite3.Row) -> Chunk:
        keys = r.keys()
        return Chunk(
            id=r["id"],
            document_id=r["document_id"],
            ordinal=r["ordinal"],
            text=r["text"],
            title=(r["doc_title"] if "doc_title" in keys else "") or "",
        )
