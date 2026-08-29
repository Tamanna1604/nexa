"""Nexa - a personal AI assistant built from first principles.

The package is organised in layers so the "brain" never depends on a concrete
database, model runtime, or retrieval library:

    providers/   -> LLM + embedding model interfaces (Ollama implementation)
    storage/     -> structured store + vector store interfaces (SQLite + Chroma)
    rag/         -> semantic chunking, hybrid retrieval, reranking, ingestion
    memory/      -> short-term + long-term memory, extraction, orchestration
    brain.py     -> assembles context from memory + RAG and talks to the LLM
    api/         -> FastAPI app exposing the brain to the web frontend
"""

__version__ = "2.0.0"
