"""Orchestrates the two memory tiers for the brain.

`context_for()` is called BEFORE the LLM to gather what Nexa knows.
`observe()` is called AFTER, to record the turn and consolidate new facts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from nexa.config import settings
from nexa.memory.extractor import MemoryExtractor
from nexa.memory.long_term import LongTermMemory
from nexa.memory.reconciler import MemoryReconciler
from nexa.memory.short_term import ShortTermMemory
from nexa.models import Memory
from nexa.providers.base import Message
from nexa.tools import current_time_string


@dataclass
class MemoryContext:
    short_term: list[Message] = field(default_factory=list)   # recent chat turns
    long_term: list[Memory] = field(default_factory=list)     # recalled durable facts

    def long_term_block(self) -> str:
        if not self.long_term:
            return ""
        lines = "\n".join(f"- ({m.memory_type}) {m.text}" for m in self.long_term)
        return (
            "Private background notes about the user, retrieved because they may "
            "relate to this message. Treat them as silent context: use a note "
            "only if it directly helps answer what was asked. Never list them, "
            "never say 'I remember' or 'you told me', and never bring them up "
            "unprompted.\n"
            f"{lines}"
        )


@dataclass
class ConsolidationResult:
    stored: list[Memory] = field(default_factory=list)
    forgotten: list[Memory] = field(default_factory=list)


_RELATIVE = re.compile(
    r"\b(this morning|this afternoon|this evening|tonight|today|just now|"
    r"right now|earlier today|a moment ago|a while ago)\b",
    re.IGNORECASE,
)
_HAS_ABS_DATE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\b|\b20\d\d\b",
)


def _anchor_relative_time(text: str, now: str) -> str:
    """Append the absolute date to an activity fact that only says 'this morning'
    etc. `now` looks like 'Saturday, 29 August 2026, 03:42 PM IST'."""
    if _HAS_ABS_DATE.search(text) or not _RELATIVE.search(text):
        return text
    m = re.match(r"([A-Za-z]+,\s*\d{1,2}\s+[A-Za-z]+\s+\d{4})", now or "")
    return f"{text} (on {m.group(1)})" if m else text


class MemoryManager:
    def __init__(
        self,
        short_term: ShortTermMemory,
        long_term: LongTermMemory,
        extractor: MemoryExtractor,
        reconciler: MemoryReconciler,
        *,
        extraction_enabled: bool | None = None,
    ) -> None:
        self.short_term = short_term
        self.long_term = long_term
        self._extractor = extractor
        self._reconciler = reconciler
        self._extraction_enabled = (
            settings.MEMORY_EXTRACTION if extraction_enabled is None else extraction_enabled
        )

    def context_for(
        self, query: str, conversation_id: str, *, recall_long_term: bool = True
    ) -> MemoryContext:
        return MemoryContext(
            short_term=self.short_term.history(conversation_id),
            long_term=self.long_term.recall(query) if recall_long_term else [],
        )

    def record_user(self, conversation_id: str, content: str) -> None:
        self.short_term.record(conversation_id, "user", content)

    def record_assistant(self, conversation_id: str, content: str) -> None:
        self.short_term.record(conversation_id, "assistant", content)

    def consolidate(
        self,
        user_message: str,
        assistant_message: str,
        conversation_id: str | None = None,
    ) -> ConsolidationResult:
        """Reconcile (delete now-wrong memories), then extract + store new ones."""
        result = ConsolidationResult()
        if not self._extraction_enabled:
            return result

        # give the extractor the last few turns so it can resolve "he"/"there"
        prior: list = []
        if conversation_id:
            prior = self.short_term.history(conversation_id)[:-1]  # exclude this turn

        # 1. does this turn correct, change, or contradict anything stored?
        related = self.long_term.related(user_message)
        related_by_id = {m.id: m for m in related}
        for change in self._reconciler.review(user_message, assistant_message, related):
            old = related_by_id.get(change.id)
            if old is None:
                continue
            if change.action == "delete":
                if self.long_term.forget(change.id):
                    result.forgotten.append(old)
            elif change.action == "update":
                new = self.long_term.update(change.id, change.text)
                if new is not None:
                    result.forgotten.append(old)
                    result.stored.append(new)

        # 2. store any new durable facts from the turn (pass the related memories
        #    so the extractor uses known name spellings and doesn't duplicate)
        now = current_time_string(settings.TIMEZONE)
        for fact in self._extractor.extract(
            user_message, assistant_message, prior, now, known=related
        ):
            text = _anchor_relative_time(fact["text"], now) if fact["type"] == "activity" else fact["text"]
            mem = self.long_term.remember(
                text, fact["type"], fact["importance"], dedupe=True
            )
            if mem is not None:
                result.stored.append(mem)
        return result
