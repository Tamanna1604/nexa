"""Cross-encoder reranking with fastembed (ONNX, no PyTorch).

A bi-encoder (Chroma, BM25) embeds the query and the document separately, so it
can only approximate their relationship. A cross-encoder feeds the pair
``[query, chunk]`` through the transformer together and outputs a single
relevance score - much more accurate, much slower. So we only run it on the
~40 candidates hybrid search already narrowed down to.

The model (~90 MB) downloads on first use and is cached under
``.fastembed_cache/``. Loading is lazy so importing Nexa stays fast.
"""

from __future__ import annotations

from typing import Sequence

from nexa.config import settings
from nexa.models import Chunk
from nexa.rag.base import Reranker


class FastEmbedReranker(Reranker):
    def __init__(self, model_name: str | None = None) -> None:
        self._model_name = model_name or settings.RERANKER_MODEL
        self._encoder = None  # lazy

    def _ensure_loaded(self):
        if self._encoder is None:
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            self._encoder = TextCrossEncoder(model_name=self._model_name)
        return self._encoder

    def warmup(self) -> None:
        """Download + load the model now (so the first real query isn't slow)."""
        try:
            list(self._ensure_loaded().rerank("warm up", ["warm up text"]))
        except Exception:
            pass

    def rerank(self, query: str, candidates: Sequence[Chunk], top_n: int) -> list[Chunk]:
        candidates = list(candidates)
        if not candidates:
            return []

        encoder = self._ensure_loaded()
        scores = list(encoder.rerank(query, [c.text for c in candidates]))

        for chunk, score in zip(candidates, scores):
            chunk.score = float(score)

        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates[:top_n]
