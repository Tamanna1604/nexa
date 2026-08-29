"""Ollama-backed implementations of the model interfaces.

Everything here talks to a local Ollama server. The rest of Nexa does not
know that.
"""

from __future__ import annotations

import re
from typing import Iterator

import ollama

from nexa.config import settings
from nexa.providers.base import EmbeddingModel, LLMClient, Message, Vector

_THINK_BLOCK = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


def _client() -> ollama.Client:
    return ollama.Client(host=settings.OLLAMA_HOST) if settings.OLLAMA_HOST else ollama.Client()


def _strip_think(text: str) -> str:
    """Remove any <think>...</think> the model leaked into `content`."""
    return _THINK_BLOCK.sub("", text).strip()


class OllamaLLM(LLMClient):
    def __init__(self, model: str | None = None) -> None:
        self.model = model or settings.MODEL_NAME
        self._c = _client()
        self._think = settings.LLM_THINK
        self._options = {
            "num_predict": settings.LLM_NUM_PREDICT,
            "temperature": settings.LLM_TEMPERATURE,
        }

    def chat(self, messages: list[Message]) -> str:
        response = self._c.chat(
            model=self.model, messages=messages, think=self._think, options=self._options
        )
        return _strip_think(response["message"]["content"])

    def stream_chat(self, messages: list[Message]) -> Iterator[str]:
        stream = self._c.chat(
            model=self.model,
            messages=messages,
            stream=True,
            think=self._think,
            options=self._options,
        )
        # With think=True the reasoning arrives under message.thinking, which we
        # never read here - so only the real answer is yielded. The suppression
        # below is a fallback for models that inline <think> tags into content.
        in_think = False
        for chunk in stream:
            piece = chunk.get("message", {}).get("content", "")
            if not piece:
                continue
            if "<think>" in piece:
                in_think = True
            if in_think:
                if "</think>" in piece:
                    in_think = False
                    piece = piece.split("</think>", 1)[1]
                else:
                    continue
            if piece:
                yield piece


class OllamaEmbeddings(EmbeddingModel):
    def __init__(self, model: str | None = None) -> None:
        self.model = model or settings.EMBEDDING_MODEL
        self._c = _client()

    def embed(self, texts: list[str]) -> list[Vector]:
        if not texts:
            return []
        # Ollama's embed endpoint accepts a list and returns one vector per item.
        response = self._c.embed(model=self.model, input=texts)
        return list(response["embeddings"])
