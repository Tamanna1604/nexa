"""Interfaces for the swappable pieces of the RAG stack."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from nexa.models import Chunk


class SparseRetriever(ABC):
    """Keyword / lexical retrieval (today: BM25)."""

    @abstractmethod
    def rebuild(self, chunks: Sequence[Chunk]) -> None:
        """(Re)build the index from the full chunk corpus."""

    @abstractmethod
    def search(self, query: str, top_k: int) -> list[tuple[str, float]]:
        """Return [(chunk_id, score)] best-first."""


class Reranker(ABC):
    """Cross-encoder relevance scoring of a candidate list."""

    @abstractmethod
    def rerank(self, query: str, candidates: Sequence[Chunk], top_n: int) -> list[Chunk]:
        """Return the top_n candidates, re-ordered, with `.score` set."""
