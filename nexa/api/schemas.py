"""Request / response bodies for the HTTP API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    conversation_id: str | None = None


class SourceView(BaseModel):
    title: str
    text: str
    score: float


class MemoryView(BaseModel):
    text: str
    type: str
    importance: int
    score: float


class ChatResponse(BaseModel):
    conversation_id: str
    reply: str
    sources: list[SourceView] = []
    memories_recalled: list[MemoryView] = []
    memories_stored: list[MemoryView] = []
    memories_forgotten: list[MemoryView] = []


class IngestFileResult(BaseModel):
    path: str
    status: str
    chunks: int = 0
    detail: str = ""


class IngestResponse(BaseModel):
    results: list[IngestFileResult]
    total_chunks: int


class DocumentView(BaseModel):
    id: str
    title: str
    path: str
    created_at: str


class MessageView(BaseModel):
    role: str
    content: str
    created_at: str


class MemoryRecordView(BaseModel):
    id: str
    text: str
    type: str
    importance: int
    use_count: int
    created_at: str
