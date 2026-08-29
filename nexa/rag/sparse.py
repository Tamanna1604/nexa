"""BM25 keyword retrieval.

BM25 scores a document for a query by, roughly:
  * term frequency in the doc (with diminishing returns), times
  * inverse document frequency (rare words count more), with
  * a length normalisation so long docs don't win by default.

`rank_bm25` keeps the whole index in memory. For a personal document corpus
that is completely fine; we just rebuild it on startup and after each upload.
"""

from __future__ import annotations

import re
from typing import Sequence

from rank_bm25 import BM25Okapi

from nexa.models import Chunk
from nexa.rag.base import SparseRetriever

_TOKEN = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "of", "to", "in", "on", "for",
    "is", "are", "was", "were", "be", "been", "it", "this", "that", "these",
    "those", "with", "as", "at", "by", "from", "into", "about", "i", "you",
    "he", "she", "they", "we", "my", "your",
}


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOPWORDS]


class BM25Retriever(SparseRetriever):
    def __init__(self) -> None:
        self._bm25: BM25Okapi | None = None
        self._chunk_ids: list[str] = []

    def rebuild(self, chunks: Sequence[Chunk]) -> None:
        self._chunk_ids = [c.id for c in chunks]
        corpus = [tokenize(c.text) for c in chunks]
        # BM25Okapi rejects an empty corpus; guard it.
        self._bm25 = BM25Okapi(corpus) if corpus else None

    def search(self, query: str, top_k: int) -> list[tuple[str, float]]:
        if self._bm25 is None or not self._chunk_ids:
            return []
        tokens = tokenize(query)
        if not tokens:
            return []
        scores = self._bm25.get_scores(tokens)
        ranked = sorted(
            zip(self._chunk_ids, scores), key=lambda pair: pair[1], reverse=True
        )
        return [(cid, float(score)) for cid, score in ranked[:top_k] if score > 0.0]
