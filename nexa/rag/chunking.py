"""Semantic chunking.

Instead of cutting every N characters, we cut where the *meaning* changes:

  1. split the document into sentences
  2. for each sentence, build a small window (sentence i-1 + i + i+1) and embed it
  3. cosine-distance between consecutive windows = "how much the topic moved"
  4. a distance above the Nth percentile of all distances is a chunk boundary
  5. guardrails: merge chunks below MIN_CHUNK_SENTENCES, hard-split above MAX_CHUNK_CHARS

Uses the same embedding model as the rest of Nexa - no extra dependency.
"""

from __future__ import annotations

import re

import numpy as np

from nexa.config import settings
from nexa.providers.base import EmbeddingModel

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n{2,}")


def split_sentences(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").strip()
    if not text:
        return []
    parts = _SENTENCE_SPLIT.split(text)
    return [p.strip() for p in parts if p and p.strip()]


def _cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0.0:
        return 1.0
    return 1.0 - float(np.dot(a, b) / denom)


class SemanticChunker:
    def __init__(
        self,
        embedder: EmbeddingModel,
        *,
        percentile: int | None = None,
        context_window: int | None = None,
        min_sentences: int | None = None,
        max_chars: int | None = None,
    ) -> None:
        self._embed = embedder
        self._percentile = percentile or settings.BREAKPOINT_PERCENTILE
        self._window = settings.CHUNK_CONTEXT_WINDOW if context_window is None else context_window
        self._min_sentences = min_sentences or settings.MIN_CHUNK_SENTENCES
        self._max_chars = max_chars or settings.MAX_CHUNK_CHARS

    def split(self, text: str) -> list[str]:
        sentences = split_sentences(text)
        if len(sentences) <= self._min_sentences:
            return ["\n".join(sentences)] if sentences else []

        # Step 2: windowed sentences -> embeddings
        windows = [
            " ".join(sentences[max(0, i - self._window): i + self._window + 1])
            for i in range(len(sentences))
        ]
        vectors = [np.asarray(v, dtype=np.float32) for v in self._embed.embed(windows)]

        # Step 3: consecutive distances
        distances = [
            _cosine_distance(vectors[i], vectors[i + 1]) for i in range(len(vectors) - 1)
        ]
        if not distances:
            return ["\n".join(sentences)]

        # Step 4: percentile threshold -> boundary indices
        threshold = float(np.percentile(distances, self._percentile))
        boundaries = {i + 1 for i, d in enumerate(distances) if d > threshold}

        # Step 5a: assemble sentence groups at the boundaries
        groups: list[list[str]] = []
        current: list[str] = []
        for i, sentence in enumerate(sentences):
            if i in boundaries and current:
                groups.append(current)
                current = []
            current.append(sentence)
        if current:
            groups.append(current)

        groups = self._merge_small(groups)
        chunks: list[str] = []
        for group in groups:
            chunks.extend(self._hard_split("\n".join(group)))
        return [c for c in chunks if c.strip()]

    def _merge_small(self, groups: list[list[str]]) -> list[list[str]]:
        merged: list[list[str]] = []
        for group in groups:
            if merged and len(merged[-1]) < self._min_sentences:
                merged[-1].extend(group)
            else:
                merged.append(list(group))
        return merged

    def _hard_split(self, chunk: str) -> list[str]:
        if len(chunk) <= self._max_chars:
            return [chunk]
        out, buf = [], ""
        for sentence in chunk.split("\n"):
            if buf and len(buf) + len(sentence) + 1 > self._max_chars:
                out.append(buf)
                buf = sentence
            else:
                buf = f"{buf}\n{sentence}".strip()
        if buf:
            out.append(buf)
        return out
