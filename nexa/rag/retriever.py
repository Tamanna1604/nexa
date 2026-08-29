"""Hybrid retrieval = dense (vectors) + sparse (BM25), fused by rank.

Reciprocal Rank Fusion (RRF) avoids the "incomparable score scales" problem:
instead of trying to normalise a cosine similarity against a BM25 score, we
only look at each item's *rank* in each list.

    RRF(item) = sum over lists of  1 / (RRF_K + rank_in_that_list)

Appearing high in either list helps; appearing in both lists helps more.
"""

from __future__ import annotations

from nexa.config import settings
from nexa.models import Chunk
from nexa.providers.base import EmbeddingModel
from nexa.rag.base import SparseRetriever
from nexa.storage.base import StructuredStore, VectorStore


def reciprocal_rank_fusion(
    ranked_lists: list[list[str]], k: int = 60
) -> list[tuple[str, float]]:
    """Fuse several best-first id lists into one. Returns [(id, score)]."""
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, item_id in enumerate(ranked):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda pair: pair[1], reverse=True)


class HybridRetriever:
    def __init__(
        self,
        store: StructuredStore,
        vectors: VectorStore,
        embedder: EmbeddingModel,
        sparse: SparseRetriever,
    ) -> None:
        self._store = store
        self._vectors = vectors
        self._embed = embedder
        self._sparse = sparse
        self._collection = settings.CHUNK_COLLECTION

    def dense_search(self, query: str) -> list[tuple[str, float]]:
        vector = self._embed.embed_one(query)
        return self._vectors.query(self._collection, vector, top_k=settings.DENSE_TOP_K)

    def sparse_search(self, query: str) -> list[tuple[str, float]]:
        return self._sparse.search(query, top_k=settings.SPARSE_TOP_K)

    def retrieve(self, query: str) -> list[Chunk]:
        dense = self.dense_search(query)
        sparse = self.sparse_search(query)
        if not dense and not sparse:
            return []

        fused = reciprocal_rank_fusion(
            [[cid for cid, _ in dense], [cid for cid, _ in sparse]],
            k=settings.RRF_K,
        )
        top_ids = [cid for cid, _ in fused[: settings.RERANK_CANDIDATES]]
        fused_scores = dict(fused)

        chunks = self._store.get_chunks(top_ids)
        for chunk in chunks:
            chunk.score = fused_scores.get(chunk.id, 0.0)
        return chunks
