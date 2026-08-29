"""FastAPI application factory.

On startup it builds ONE `Nexa` (shared across requests), creates the DB
tables, ingests the `documents/` folder, and builds the BM25 index. The
frontend is served as static files from `/`.
"""

from __future__ import annotations

import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from nexa.api.routes import router
from nexa.brain import build_nexa
from nexa.config import ROOT, settings

FRONTEND_DIR = ROOT / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    bundle = build_nexa()
    print("[nexa] bootstrapping - creating tables, ingesting documents, building BM25 ...")
    bundle.bootstrap(ingest=True)
    print(
        f"[nexa] ready - {len(bundle.store.all_chunks())} chunks, "
        f"{len(bundle.store.list_documents())} documents indexed."
    )
    app.state.bundle = bundle

    # Load the reranker in the background so the first spoken question doesn't
    # also pay the ~90 MB model download.
    def _warm() -> None:
        print("[nexa] warming up the reranker model in the background ...")
        bundle.nexa.rag.warmup()
        print("[nexa] reranker ready.")

    threading.Thread(target=_warm, daemon=True).start()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Nexa", version="2.0.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],   # dev only; a personal assistant on localhost
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)

    if FRONTEND_DIR.exists():
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

    return app


app = create_app()
