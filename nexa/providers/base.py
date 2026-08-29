"""Interfaces for the two model capabilities Nexa needs.

The brain and the RAG layer only ever import THESE classes, never `ollama`.
To move Nexa onto OpenAI / llama.cpp / vLLM you write one new subclass and
change one line in `nexa/brain.py`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator

# A chat message is the usual {"role": "system"|"user"|"assistant", "content": str}.
Message = dict[str, str]
Vector = list[float]


class LLMClient(ABC):
    """A text-in / text-out conversational model."""

    @abstractmethod
    def chat(self, messages: list[Message]) -> str:
        """Return the full assistant reply for a message list."""

    @abstractmethod
    def stream_chat(self, messages: list[Message]) -> Iterator[str]:
        """Yield the assistant reply token-by-token (for live typing)."""


class EmbeddingModel(ABC):
    """Turns text into vectors for semantic search."""

    @abstractmethod
    def embed(self, texts: list[str]) -> list[Vector]:
        """Embed a batch of texts. Order of output matches input."""

    def embed_one(self, text: str) -> Vector:
        """Convenience wrapper for a single string."""
        return self.embed([text])[0]
