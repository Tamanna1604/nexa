"""The read path: query -> hybrid retrieve -> rerank -> grounded context.

    query
      |
      v
  HybridRetriever   (dense + sparse, fused by RRF)   -> ~40 candidate chunks
      |
      v
  FastEmbedReranker (cross-encoder)                   -> top 5, re-ordered
      |
      v
  score floor filter                                  -> maybe 0 chunks
      |
      v
  build_context()                                     -> string for the prompt
"""

from __future__ import annotations

from nexa.config import settings
from nexa.models import Chunk
from nexa.rag.base import Reranker
from nexa.rag.retriever import HybridRetriever


class RAGPipeline:
    def __init__(self, retriever: HybridRetriever, reranker: Reranker) -> None:
        self._retriever = retriever
        self._reranker = reranker

    def warmup(self) -> None:
        warm = getattr(self._reranker, "warmup", None)
        if callable(warm):
            warm()

    def retrieve(self, query: str) -> list[Chunk]:
        candidates = self._retriever.retrieve(query)
        if not candidates:
            return []

        reranked = self._reranker.rerank(
            query, candidates, top_n=settings.FINAL_CONTEXT_N
        )
        if not reranked:
            return []

        # Nothing is relevant enough -> inject no document context at all.
        if reranked[0].score < settings.RERANK_SCORE_FLOOR:
            return []
        # Keep the best, plus any other chunk that also clears the floor.
        kept = [c for c in reranked if c.score >= settings.RERANK_SCORE_FLOOR]
        return kept or reranked[:1]

    @staticmethod
    def build_context(chunks: list[Chunk]) -> str:
        if not chunks:
            return ""
        blocks = []
        for i, chunk in enumerate(chunks, 1):
            source = chunk.title or "document"
            blocks.append(f"[{i}] (source: {source})\n{chunk.text}")
        body = "\n\n".join(blocks)
        return (
            "Passages retrieved from the user's documents. Use them to answer if "
            "relevant, and mention the source title:\n\n" + body
        )
