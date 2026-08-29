"""HTTP endpoints. All state lives on `request.app.state.bundle` (one Nexa)."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from nexa.config import settings
from nexa.api.schemas import (
    ChatRequest,
    ChatResponse,
    DocumentView,
    IngestResponse,
    MemoryRecordView,
    MessageView,
)
from nexa.brain import _chunk_view, _memory_view

router = APIRouter(prefix="/api")


def _bundle(request: Request):
    return request.app.state.bundle


@router.get("/health")
def health(request: Request) -> dict:
    bundle = _bundle(request)
    return {
        "status": "ok",
        "model": settings.MODEL_NAME,
        "chunks_indexed": len(bundle.store.all_chunks()),
        "documents": len(bundle.store.list_documents()),
    }


@router.post("/chat", response_model=ChatResponse)
def chat(request: Request, body: ChatRequest) -> ChatResponse:
    result = _bundle(request).nexa.respond(body.message, body.conversation_id)
    return ChatResponse(
        conversation_id=result.conversation_id,
        reply=result.reply,
        sources=[_chunk_view(c) for c in result.sources],
        memories_recalled=[_memory_view(m) for m in result.memories_recalled],
        memories_stored=[_memory_view(m) for m in result.memories_stored],
        memories_forgotten=[_memory_view(m) for m in result.memories_forgotten],
    )


@router.post("/chat/stream")
def chat_stream(request: Request, body: ChatRequest) -> StreamingResponse:
    nexa = _bundle(request).nexa

    def event_source():
        for event in nexa.respond_stream(body.message, body.conversation_id):
            etype = event.pop("type")
            yield f"event: {etype}\ndata: {json.dumps(event)}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/ingest", response_model=IngestResponse)
async def ingest(request: Request, file: UploadFile) -> IngestResponse:
    bundle = _bundle(request)
    name = Path(file.filename or "").name
    suffix = Path(name).suffix.lower()
    if not name or suffix not in {".txt", ".md", ".markdown", ".pdf"}:
        raise HTTPException(400, f"Unsupported file type: {suffix or 'unknown'}")

    docs_dir = Path(settings.DOCUMENTS_DIR)
    docs_dir.mkdir(parents=True, exist_ok=True)
    target = docs_dir / name
    target.write_bytes(await file.read())

    result = bundle.ingestion.ingest_file(target)
    bundle.sparse.rebuild(bundle.store.all_chunks())
    return IngestResponse(
        results=[result.__dict__],
        total_chunks=result.chunks,
    )


@router.get("/documents", response_model=list[DocumentView])
def documents(request: Request) -> list[DocumentView]:
    return [
        DocumentView(id=d.id, title=d.title, path=d.path, created_at=d.created_at)
        for d in _bundle(request).store.list_documents()
    ]


@router.get("/memories", response_model=list[MemoryRecordView])
def list_memories(request: Request) -> list[MemoryRecordView]:
    ltm = _bundle(request).nexa.memory.long_term
    return [
        MemoryRecordView(
            id=m.id,
            text=m.text,
            type=m.memory_type,
            importance=m.importance,
            use_count=m.use_count,
            created_at=m.created_at,
        )
        for m in sorted(ltm.all(), key=lambda m: m.created_at, reverse=True)
    ]


@router.delete("/memories/{memory_id}")
def forget_memory(request: Request, memory_id: str) -> dict:
    ltm = _bundle(request).nexa.memory.long_term
    if not ltm.forget(memory_id):
        raise HTTPException(404, "memory not found")
    return {"forgotten": memory_id}


@router.delete("/memories")
def forget_all_memories(request: Request) -> dict:
    removed = _bundle(request).nexa.memory.long_term.forget_all()
    return {"forgotten": removed}


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageView])
def conversation_messages(request: Request, conversation_id: str) -> list[MessageView]:
    store = _bundle(request).store
    if not store.conversation_exists(conversation_id):
        raise HTTPException(404, "conversation not found")
    return [
        MessageView(role=m.role, content=m.content, created_at=m.created_at)
        for m in store.all_messages(conversation_id)
    ]
