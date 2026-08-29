"""Storage interfaces.

`StructuredStore`  -> rows, relations, exact lookups (today: SQLite).
`VectorStore`      -> embeddings + nearest-neighbour search (today: Chroma).

Swapping to Postgres or Qdrant means writing a new subclass here and changing
the wiring in `nexa/brain.py` / `nexa/api/app.py`. Nothing else changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Sequence

from nexa.models import Chunk, ChatMessage, Document, Memory
from nexa.providers.base import Vector


class StructuredStore(ABC):
    # ---- lifecycle ----
    @abstractmethod
    def setup(self) -> None:
        """Create tables / run migrations. Safe to call repeatedly."""

    # ---- conversations & messages (short-term memory lives here) ----
    @abstractmethod
    def create_conversation(self, title: str = "") -> str: ...

    @abstractmethod
    def conversation_exists(self, conversation_id: str) -> bool: ...

    @abstractmethod
    def add_message(self, conversation_id: str, role: str, content: str) -> ChatMessage: ...

    @abstractmethod
    def recent_messages(self, conversation_id: str, limit: int) -> list[ChatMessage]:
        """Most recent `limit` messages, returned oldest-first."""

    @abstractmethod
    def all_messages(self, conversation_id: str) -> list[ChatMessage]: ...

    # ---- long-term memories ----
    @abstractmethod
    def add_memory(self, memory: Memory) -> None: ...

    @abstractmethod
    def all_memories(self) -> list[Memory]: ...

    @abstractmethod
    def get_memory(self, memory_id: str) -> Memory | None: ...

    @abstractmethod
    def delete_memory(self, memory_id: str) -> None: ...

    @abstractmethod
    def touch_memory(self, memory_id: str, used_at: str) -> None:
        """Record that a memory was retrieved (bumps use_count + last_used_at)."""

    # ---- RAG documents & chunks ----
    @abstractmethod
    def get_document_by_hash(self, content_hash: str) -> Document | None: ...

    @abstractmethod
    def get_document_by_path(self, path: str) -> Document | None: ...

    @abstractmethod
    def add_document(self, document: Document) -> None: ...

    @abstractmethod
    def delete_document(self, document_id: str) -> list[str]:
        """Delete a document + its chunks. Returns the deleted chunk ids."""

    @abstractmethod
    def add_chunks(self, chunks: Sequence[Chunk]) -> None: ...

    @abstractmethod
    def all_chunks(self) -> list[Chunk]:
        """Every chunk in the corpus - used to (re)build the BM25 index."""

    @abstractmethod
    def get_chunks(self, chunk_ids: Sequence[str]) -> list[Chunk]:
        """Hydrate chunk rows by id, preserving the requested order."""

    @abstractmethod
    def list_documents(self) -> list[Document]: ...


class VectorStore(ABC):
    @abstractmethod
    def add(
        self,
        collection: str,
        ids: Sequence[str],
        embeddings: Sequence[Vector],
        documents: Sequence[str],
        metadatas: Sequence[dict[str, Any]] | None = None,
    ) -> None: ...

    @abstractmethod
    def query(
        self,
        collection: str,
        embedding: Vector,
        top_k: int,
        where: dict[str, Any] | None = None,
    ) -> list[tuple[str, float]]:
        """Return [(id, similarity)] best-first. Similarity in [0, 1]."""

    @abstractmethod
    def delete(self, collection: str, ids: Sequence[str]) -> None: ...

    def ensure_space(self, collection: str, space: str = "cosine") -> bool:
        """Make sure `collection` uses the given distance metric.

        Returns True if the collection had to be dropped and recreated (meaning
        the caller must re-populate it). Default implementation is a no-op for
        stores where the metric is fixed.
        """
        return False
