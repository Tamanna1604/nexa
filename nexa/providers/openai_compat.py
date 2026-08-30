"""One LLM client for every OpenAI-compatible hosted API.

Groq, Cerebras, OpenRouter, Gemini (via its compat endpoint) and OpenAI all
expose the same `POST /chat/completions` shape, so a single class covers them -
pick one with `LLM_BACKEND` in `.env`, supply the matching API key.

Uses `httpx` (already a dependency via ollama/fastapi) - no new package.
"""

from __future__ import annotations

import json
import re
import time
from typing import Iterator

import httpx

from nexa.config import settings
from nexa.providers.base import LLMClient, Message

_MAX_RETRIES = 4


def _retry_after_seconds(resp: httpx.Response) -> float:
    """How long to wait after a 429, from the header or the error message."""
    header = resp.headers.get("retry-after")
    if header:
        try:
            return min(30.0, float(header))
        except ValueError:
            pass
    m = re.search(r"try again in ([\d.]+)\s*s", resp.text)
    return min(30.0, float(m.group(1)) + 0.3) if m else 5.0

# backend name -> base URL (no trailing slash)
PROVIDERS: dict[str, str] = {
    "groq": "https://api.groq.com/openai/v1",
    "cerebras": "https://api.cerebras.ai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "openai": "https://api.openai.com/v1",
}


def _resolve_base_url(backend: str) -> str:
    if settings.LLM_BASE_URL:
        return settings.LLM_BASE_URL.rstrip("/")
    if backend not in PROVIDERS:
        raise ValueError(
            f"Unknown LLM_BACKEND {backend!r}. Known: {', '.join(PROVIDERS)} "
            f"(or set LLM_BASE_URL explicitly)."
        )
    return PROVIDERS[backend]


def _resolve_api_key(backend: str) -> str:
    # accept either the generic LLM_API_KEY or a provider-specific one
    candidates = [
        settings.LLM_API_KEY,
        getattr(settings, f"{backend.upper()}_API_KEY", None),
    ]
    for key in candidates:
        if key:
            return key
    raise ValueError(
        f"No API key for backend {backend!r}. Set {backend.upper()}_API_KEY "
        f"(or LLM_API_KEY) in your .env."
    )


class OpenAICompatibleLLM(LLMClient):
    def __init__(self, backend: str | None = None, model: str | None = None) -> None:
        self.backend = backend or settings.LLM_BACKEND
        self.model = model or settings.MODEL_NAME
        self._base = _resolve_base_url(self.backend)
        self._key = _resolve_api_key(self.backend)
        self._client = httpx.Client(timeout=httpx.Timeout(120.0, connect=10.0))

    def _headers(self) -> dict[str, str]:
        h = {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}
        if self.backend == "openrouter":
            h["HTTP-Referer"] = "http://localhost"
            h["X-Title"] = "Nexa"
        return h

    def _body(self, messages: list[Message], stream: bool) -> dict:
        return {
            "model": self.model,
            "messages": messages,
            "stream": stream,
            "temperature": settings.LLM_TEMPERATURE,
            "max_tokens": settings.LLM_NUM_PREDICT,
        }

    # ------------------------------------------------------------------
    def chat(self, messages: list[Message]) -> str:
        return self.chat_raw(messages).get("content") or ""

    def chat_raw(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        tool_choice: str | dict | None = None,
    ) -> dict:
        """One non-streamed turn. Returns {'content': str|None, 'tool_calls': [...]}.

        `tool_calls` is populated when the model wants to call a tool instead of
        answering - see the loop in `nexa/brain.py`. `tool_choice` defaults to
        "auto"; pass {"type":"function","function":{"name":...}} to force one.
        Retries on 429 (rate limit).
        """
        body = self._body(messages, stream=False)
        if tools:
            body["tools"] = tools
            body["tool_choice"] = tool_choice or "auto"

        for attempt in range(_MAX_RETRIES):
            r = self._client.post(
                f"{self._base}/chat/completions", headers=self._headers(), json=body
            )
            if r.status_code == 429 and attempt < _MAX_RETRIES - 1:
                wait = _retry_after_seconds(r)
                print(f"[nexa] {self.backend} rate-limited, retrying in {wait:.0f}s")
                time.sleep(wait)
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"{self.backend} error {r.status_code}: {r.text}")
            msg = r.json()["choices"][0]["message"]
            return {"content": msg.get("content"), "tool_calls": msg.get("tool_calls") or []}
        raise RuntimeError(f"{self.backend}: still rate-limited after {_MAX_RETRIES} tries")

    def stream_chat(self, messages: list[Message]) -> Iterator[str]:
        body = self._body(messages, stream=True)
        for attempt in range(_MAX_RETRIES):
            with self._client.stream(
                "POST", f"{self._base}/chat/completions", headers=self._headers(), json=body
            ) as r:
                if r.status_code == 429 and attempt < _MAX_RETRIES - 1:
                    text = r.read().decode()
                    m = re.search(r"try again in ([\d.]+)\s*s", text)
                    wait = min(30.0, float(m.group(1)) + 0.3) if m else 5.0
                    print(f"[nexa] {self.backend} rate-limited, retrying in {wait:.0f}s")
                    time.sleep(wait)
                    continue
                if r.status_code >= 400:
                    raise RuntimeError(f"{self.backend} error {r.status_code}: {r.read().decode()}")
                yield from self._stream_lines(r)
                return

    @staticmethod
    def _stream_lines(r: httpx.Response) -> Iterator[str]:
        for line in r.iter_lines():
            if not line or not line.startswith("data:"):
                continue
            payload = line[len("data:"):].strip()
            if payload == "[DONE]":
                break
            try:
                chunk = json.loads(payload)
            except json.JSONDecodeError:
                continue
            choices = chunk.get("choices") or []
            if not choices:
                continue
            piece = (choices[0].get("delta") or {}).get("content") or ""
            if piece:
                yield piece
