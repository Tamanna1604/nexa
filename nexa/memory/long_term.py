"""Long-term memory = durable facts about the user.

Stored twice, on purpose:
  * structured store  -> the row of record (type, importance, usage stats)
  * vector store      -> semantic recall ("what's my sister's name?")

Recall ranks candidates with a small weighted formula rather than raw
similarity, so an important, frequently-used, recent fact can outrank a
slightly-more-similar throwaway.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone

from nexa.config import settings
from nexa.models import Memory
from nexa.providers.base import EmbeddingModel
from nexa.storage.base import StructuredStore, VectorStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _age_days(iso: str | None) -> float:
    if not iso:
        return 9_999.0
    try:
        then = datetime.fromisoformat(iso)
        if then.tzinfo is None:
            then = then.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - then).total_seconds() / 86_400)
    except ValueError:
        return 9_999.0


class LongTermMemory:
    def __init__(
        self,
        store: StructuredStore,
        vectors: VectorStore,
        embedder: EmbeddingModel,
    ) -> None:
        self._store = store
        self._vectors = vectors
        self._embed = embedder
        self._collection = settings.MEMORY_COLLECTION

    # ------------------------------------------------------------------
    # write
    # ------------------------------------------------------------------
    def remember(
        self,
        text: str,
        memory_type: str = "general",
        importance: int = 5,
        *,
        dedupe: bool = True,
    ) -> Memory | None:
        text = text.strip()
        if not text:
            return None

        vector = self._embed.embed_one(text)

        if dedupe and self._is_duplicate(vector):
            return None

        memory = Memory(
            id=str(uuid.uuid4()),
            text=text,
            memory_type=memory_type,
            importance=max(1, min(10, int(importance))),
            created_at=_now(),
            last_used_at=None,
            use_count=0,
        )
        self._store.add_memory(memory)
        self._vectors.add(
            collection=self._collection,
            ids=[memory.id],
            embeddings=[vector],
            documents=[memory.text],
            metadatas=[
                {
                    "memory_type": memory.memory_type,
                    "importance": memory.importance,
                    "created_at": memory.created_at,
                }
            ],
        )
        return memory

    def _is_duplicate(self, vector: list[float]) -> bool:
        hits = self._vectors.query(self._collection, vector, top_k=1)
        return bool(hits) and hits[0][1] >= settings.MEMORY_DEDUPE_THRESHOLD

    # ------------------------------------------------------------------
    # read
    # ------------------------------------------------------------------
    def recall(self, query: str, top_k: int | None = None) -> list[Memory]:
        top_k = top_k or settings.LONG_TERM_TOP_K
        query_vec = self._embed.embed_one(query)
        # Pull a few extra candidates, then re-rank and trim.
        hits = self._vectors.query(self._collection, query_vec, top_k=top_k * 3)
        # Drop weak matches BEFORE ranking - a stale memory should not ride into
        # the prompt on importance/recency alone when it has nothing to do with
        # what was just said.
        hits = [
            (mem_id, sim)
            for mem_id, sim in hits
            if sim >= settings.LONG_TERM_MIN_SIMILARITY
        ]
        if not hits:
            return []

        by_id = {m.id: m for m in self._store.all_memories()}
        ranked: list[Memory] = []
        max_uses = max((by_id[i].use_count for i, _ in hits if i in by_id), default=0) or 1

        for mem_id, similarity in hits:
            mem = by_id.get(mem_id)
            if mem is None:
                continue
            recency = math.exp(-_age_days(mem.created_at) / 30.0)      # ~1 month half-life
            frequency = mem.use_count / max_uses
            mem.score = (
                0.60 * similarity
                + 0.20 * (mem.importance / 10.0)
                + 0.12 * recency
                + 0.08 * frequency
            )
            ranked.append(mem)

        ranked.sort(key=lambda m: m.score, reverse=True)

        # collapse exact-text duplicates (belt-and-braces on top of write-time
        # dedupe) so the model never sees the same fact twice
        chosen: list[Memory] = []
        seen: set[str] = set()
        for mem in ranked:
            key = mem.text.strip().lower()
            if key in seen:
                continue
            seen.add(key)
            chosen.append(mem)
            if len(chosen) >= top_k:
                break

        for mem in chosen:
            self._store.touch_memory(mem.id, _now())
        return chosen

    def related(self, query: str, k: int = 8, min_sim: float = 0.45) -> list[Memory]:
        """Memories loosely related to `query` (for contradiction checking).

        Wider net than recall(): a lower similarity floor, no importance ranking.
        """
        vec = self._embed.embed_one(query)
        hits = self._vectors.query(self._collection, vec, top_k=k)
        by_id = {m.id: m for m in self._store.all_memories()}
        out: list[Memory] = []
        for mem_id, sim in hits:
            if sim < min_sim:
                continue
            mem = by_id.get(mem_id)
            if mem is not None:
                mem.score = sim
                out.append(mem)
        return out

    # ------------------------------------------------------------------
    # index maintenance
    # ------------------------------------------------------------------
    def ensure_index(self) -> None:
        """Guarantee the memory vector collection uses cosine distance.

        If it had to be rebuilt (e.g. an old L2 collection from Nexa v1), we
        re-embed every memory from the structured store - which stays the
        source of truth - so nothing is lost.
        """
        rebuilt = self._vectors.ensure_space(self._collection, "cosine")
        if not rebuilt:
            return
        memories = self._store.all_memories()
        if not memories:
            return
        vectors = self._embed.embed([m.text for m in memories])
        self._vectors.add(
            collection=self._collection,
            ids=[m.id for m in memories],
            embeddings=vectors,
            documents=[m.text for m in memories],
            metadatas=[
                {
                    "memory_type": m.memory_type,
                    "importance": m.importance,
                    "created_at": m.created_at,
                }
                for m in memories
            ],
        )

    # ------------------------------------------------------------------
    # management
    # ------------------------------------------------------------------
    def all(self) -> list[Memory]:
        return self._store.all_memories()

    def forget(self, memory_id: str) -> bool:
        if self._store.get_memory(memory_id) is None:
            return False
        self._store.delete_memory(memory_id)
        self._vectors.delete(self._collection, [memory_id])
        return True

    def update(self, memory_id: str, new_text: str) -> Memory | None:
        """Replace a memory's text (re-embeds it), keeping its type/importance.

        Used when a fact changed shape but its core detail should survive
        (e.g. "boyfriend named Rohan" -> "Rohan is the user's ex-boyfriend").
        """
        old = self._store.get_memory(memory_id)
        if old is None:
            return None
        self.forget(memory_id)
        return self.remember(new_text, old.memory_type, old.importance, dedupe=False)

    def forget_all(self) -> int:
        memories = self._store.all_memories()
        for mem in memories:
            self._store.delete_memory(mem.id)
        self._vectors.delete(self._collection, [m.id for m in memories])
        return len(memories)
