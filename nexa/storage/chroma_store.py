"""ChromaDB implementation of :class:`VectorStore`.

Collections are created lazily with cosine distance (a good match for
`nomic-embed-text` output). Similarity is reported as ``1 - cosine_distance``
so callers always see "bigger = more relevant" in [0, 1].
"""

from __future__ import annotations

from typing import Any, Sequence

import chromadb

from nexa.providers.base import Vector
from nexa.storage.base import VectorStore


class ChromaVectorStore(VectorStore):
    def __init__(self, path: str) -> None:
        self._client = chromadb.PersistentClient(path=path)
        self._collections: dict[str, Any] = {}

    def _collection(self, name: str):
        if name not in self._collections:
            self._collections[name] = self._client.get_or_create_collection(
                name=name, metadata={"hnsw:space": "cosine"}
            )
        return self._collections[name]

    def add(
        self,
        collection: str,
        ids: Sequence[str],
        embeddings: Sequence[Vector],
        documents: Sequence[str],
        metadatas: Sequence[dict[str, Any]] | None = None,
    ) -> None:
        if not ids:
            return
        self._collection(collection).add(
            ids=list(ids),
            embeddings=[list(e) for e in embeddings],
            documents=list(documents),
            metadatas=list(metadatas) if metadatas else None,
        )

    def query(
        self,
        collection: str,
        embedding: Vector,
        top_k: int,
        where: dict[str, Any] | None = None,
    ) -> list[tuple[str, float]]:
        res = self._collection(collection).query(
            query_embeddings=[list(embedding)],
            n_results=top_k,
            where=where,
        )
        ids = (res.get("ids") or [[]])[0]
        distances = (res.get("distances") or [[]])[0]
        out: list[tuple[str, float]] = []
        for cid, dist in zip(ids, distances):
            similarity = 1.0 - float(dist)          # cosine distance -> similarity
            out.append((cid, max(0.0, min(1.0, similarity))))
        return out

    def delete(self, collection: str, ids: Sequence[str]) -> None:
        if not ids:
            return
        self._collection(collection).delete(ids=list(ids))

    def ensure_space(self, collection: str, space: str = "cosine") -> bool:
        """Recreate the collection if its distance metric differs from `space`.

        A collection made by an older Nexa (or by hand) may be using Chroma's
        default L2 metric, which breaks our `1 - distance` similarity math.
        """
        try:
            existing = self._client.get_collection(collection)
        except Exception:
            return False  # doesn't exist yet - it'll be made with the right space
        current = (existing.metadata or {}).get("hnsw:space", "l2")
        if current == space:
            self._collections[collection] = existing
            return False
        self._client.delete_collection(collection)
        self._collections.pop(collection, None)
        self._collections[collection] = self._client.get_or_create_collection(
            name=collection, metadata={"hnsw:space": space}
        )
        return True
