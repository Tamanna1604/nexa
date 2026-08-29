"""Short-term memory = the rolling window of the current conversation.

No embeddings, no ranking - just the last N messages read straight from the
structured store. This is what gives Nexa "working memory" within a session.
"""

from __future__ import annotations

from nexa.config import settings
from nexa.models import ChatMessage
from nexa.providers.base import Message
from nexa.storage.base import StructuredStore


class ShortTermMemory:
    def __init__(self, store: StructuredStore, window: int | None = None) -> None:
        self._store = store
        self._window = window or settings.SHORT_TERM_WINDOW

    def record(self, conversation_id: str, role: str, content: str) -> ChatMessage:
        return self._store.add_message(conversation_id, role, content)

    def history(self, conversation_id: str) -> list[Message]:
        """Recent turns as chat messages ready to hand to the LLM."""
        rows = self._store.recent_messages(conversation_id, self._window)
        return [{"role": m.role, "content": m.content} for m in rows]

    def transcript(self, conversation_id: str) -> list[ChatMessage]:
        return self._store.all_messages(conversation_id)
