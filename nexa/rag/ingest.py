"""Ingestion pipeline: file -> text -> semantic chunks -> vectors + rows.

Idempotent: a file whose content hash is unchanged is skipped. A changed file
has its old chunks (rows + vectors) deleted before re-ingesting.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from nexa.config import settings
from nexa.models import Chunk, Document
from nexa.providers.base import EmbeddingModel
from nexa.rag.chunking import SemanticChunker
from nexa.rag.loaders import discover, load_file
from nexa.storage.base import StructuredStore, VectorStore


@dataclass
class IngestResult:
    path: str
    status: str          # "ingested" | "skipped" | "empty" | "error"
    chunks: int = 0
    detail: str = ""


class IngestionPipeline:
    def __init__(
        self,
        store: StructuredStore,
        vectors: VectorStore,
        embedder: EmbeddingModel,
        chunker: SemanticChunker,
    ) -> None:
        self._store = store
        self._vectors = vectors
        self._embed = embedder
        self._chunker = chunker
        self._collection = settings.CHUNK_COLLECTION

    def ingest_directory(self, documents_dir: str | None = None) -> list[IngestResult]:
        directory = documents_dir or settings.DOCUMENTS_DIR
        found = discover(directory)
        results = [self.ingest_file(path) for path in found]
        results += self._prune_missing({str(p) for p in found})
        return results

    def _prune_missing(self, present_paths: set[str]) -> list[IngestResult]:
        """Drop documents (and their chunks/vectors) whose file is gone."""
        removed: list[IngestResult] = []
        for doc in self._store.list_documents():
            if doc.path in present_paths or Path(doc.path).exists():
                continue
            chunk_ids = self._store.delete_document(doc.id)
            self._vectors.delete(self._collection, chunk_ids)
            removed.append(IngestResult(doc.path, "removed", detail="file deleted"))
        return removed

    def ingest_file(self, path: str | Path) -> IngestResult:
        path = Path(path)
        try:
            raw = path.read_bytes()
        except OSError as exc:
            return IngestResult(str(path), "error", detail=str(exc))

        content_hash = hashlib.sha256(raw).hexdigest()
        existing = self._store.get_document_by_path(str(path))
        if existing and existing.hash == content_hash:
            return IngestResult(str(path), "skipped", detail="unchanged")

        try:
            title, text = load_file(path)
        except Exception as exc:  # noqa: BLE001 - report any loader failure
            return IngestResult(str(path), "error", detail=str(exc))

        if not text.strip():
            return IngestResult(str(path), "empty")

        # Replace a changed document.
        if existing:
            old_chunk_ids = self._store.delete_document(existing.id)
            self._vectors.delete(self._collection, old_chunk_ids)

        chunk_texts = self._chunker.split(text)
        if not chunk_texts:
            return IngestResult(str(path), "empty")

        document = Document(
            id=str(uuid.uuid4()),
            path=str(path),
            title=title,
            hash=content_hash,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        chunks = [
            Chunk(
                id=str(uuid.uuid4()),
                document_id=document.id,
                ordinal=i,
                text=chunk_text,
                title=title,
            )
            for i, chunk_text in enumerate(chunk_texts)
        ]

        embeddings = self._embed.embed([c.text for c in chunks])

        self._store.add_document(document)
        self._store.add_chunks(chunks)
        self._vectors.add(
            collection=self._collection,
            ids=[c.id for c in chunks],
            embeddings=embeddings,
            documents=[c.text for c in chunks],
            metadatas=[
                {
                    "document_id": document.id,
                    "title": title,
                    "path": str(path),
                    "ordinal": c.ordinal,
                }
                for c in chunks
            ],
        )
        return IngestResult(str(path), "ingested", chunks=len(chunks))
