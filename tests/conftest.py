"""Fakes so the test-suite never needs a running Ollama server."""

from __future__ import annotations

import hashlib

import pytest

from nexa.providers.base import EmbeddingModel, LLMClient


class FakeEmbeddingModel(EmbeddingModel):
    """Deterministic hash-based embeddings.

    Not semantically meaningful, but stable and cheap - enough to exercise the
    plumbing (chunking loop, dedupe, vector-store round trips).
    """

    DIM = 32

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            digest = hashlib.sha256(text.lower().encode()).digest()
            raw = [digest[i % len(digest)] / 255.0 for i in range(self.DIM)]
            norm = sum(v * v for v in raw) ** 0.5 or 1.0
            vectors.append([v / norm for v in raw])
        return vectors


class ScriptedLLM(LLMClient):
    """Returns queued replies in order; records what it was asked."""

    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)
        self.calls: list[list[dict]] = []

    def chat(self, messages):
        self.calls.append(messages)
        return self._replies.pop(0) if self._replies else ""

    def stream_chat(self, messages):
        for token in self.chat(messages).split():
            yield token + " "


@pytest.fixture
def fake_embedder() -> FakeEmbeddingModel:
    return FakeEmbeddingModel()
