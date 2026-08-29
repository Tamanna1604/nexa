"""Plain domain objects passed between layers.

These are deliberately dumb data holders - no behaviour, no DB awareness.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ChatMessage:
    id: str
    conversation_id: str
    role: str          # "user" | "assistant" | "system"
    content: str
    created_at: str


@dataclass
class Memory:
    id: str
    text: str
    memory_type: str            # general | preference | goal | instruction | relationship | fact
    importance: int             # 1..10
    created_at: str
    last_used_at: str | None = None
    use_count: int = 0
    score: float = 0.0          # filled in during ranking, not persisted


@dataclass
class Document:
    id: str
    path: str
    title: str
    hash: str
    created_at: str


@dataclass
class Chunk:
    id: str
    document_id: str
    ordinal: int                # position of the chunk within its document
    text: str
    title: str = ""             # denormalised document title, for display
    score: float = 0.0          # retrieval / rerank score, not persisted
    metadata: dict = field(default_factory=dict)
