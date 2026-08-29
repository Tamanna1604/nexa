# Nexa

A personal AI assistant built from first principles. The language model is only
one component — Nexa's intelligence comes from the architecture around it:
layered memory, hybrid retrieval, reranking, and (later) tools, speech, and
vision.

This is **Nexa v2**: it adds advanced RAG over your own documents, a two-tier
memory system, and a web frontend with voice input.

---

## What's in this version

| Capability | How it works |
|---|---|
| **Semantic chunking** | Documents are split on *meaning* boundaries, not fixed sizes. |
| **Hybrid retrieval** | Dense vector search **+** sparse BM25 keyword search. |
| **Rank fusion** | The two result lists are merged with Reciprocal Rank Fusion. |
| **Reranking** | A cross-encoder re-scores the merged candidates for final relevance. |
| **Short-term memory** | The last N messages of the current conversation. |
| **Long-term memory** | Durable facts an LLM extracts from finished turns; contradictions delete the stale fact. |
| **Tools** | The LLM can call `get_datetime` and `get_weather` (Open-Meteo, keyless) for live data. |
| **Voice-first UI** | No text box. Wake word "Nexa", always-listening, spoken replies, a reactive particle constellation. |

Everything sits behind interfaces (`LLMClient`, `EmbeddingModel`,
`StructuredStore`, `VectorStore`, `SparseRetriever`, `Reranker`) so the storage
and model backends can be swapped without touching the brain.

---

## Architecture

```
                          ┌──────────────┐
   your message ─────────▶│    Nexa      │
                          │   (brain)    │
                          └──────┬───────┘
              ┌──────────────────┼────────────────────┐
              ▼                  ▼                     ▼
     ShortTermMemory      LongTermMemory          RAGPipeline
   (recent messages     (semantic recall of    (hybrid retrieve
    from SQLite)          extracted facts)       → rerank → context)
              │                  │                     │
              └────────────┬─────┴──────────┬──────────┘
                           ▼                ▼
                    assembled prompt   ──▶  Local LLM (Ollama / Qwen3)
                           │                       │
                           ▼                       ▼
                   MemoryManager.observe()     streamed reply
                   (record turn + extract
                    new long-term facts)
```

### RAG read path

```
query
  │
  ▼
┌───────────────── HybridRetriever ─────────────────┐
│  dense  : embed query → Chroma nearest neighbours │  ~20
│  sparse : tokenise query → BM25 over all chunks   │  ~20
│  fuse   : Reciprocal Rank Fusion (RRF_K = 60)     │  → ~40 candidates
└───────────────────────┬───────────────────────────┘
                        ▼
              FastEmbedReranker (cross-encoder, ONNX)
                        ▼
             top 5, re-ordered, score-floor filtered
                        ▼
              build_context() → text block in the system prompt
```

### RAG write path (ingestion)

```
file (.txt / .md / .pdf)
  │  load_file()               → plain text
  ▼
SemanticChunker.split()        → list of meaning-coherent chunks
  │  embed each chunk (nomic-embed-text)
  ▼
├─ SQLiteStore   : documents + chunks rows      (source of truth, BM25 corpus)
└─ ChromaStore   : chunk vectors in `nexa_chunks` collection
  │
  ▼
BM25Retriever.rebuild()        → in-memory keyword index
```

### Why semantic chunking

1. Split the document into sentences.
2. For each sentence build a small window (`i-1 + i + i+1`) and embed it.
3. Cosine distance between consecutive windows = how much the topic moved.
4. A distance above the 95th percentile of all distances is a chunk boundary.
5. Guardrails: merge chunks under `MIN_CHUNK_SENTENCES`, hard-split over
   `MAX_CHUNK_CHARS`.

Fixed-size chunking slices sentences and mixes unrelated ideas in one chunk;
semantic chunking keeps each chunk about one thing, which makes both retrieval
and reranking sharper.

### Why hybrid + RRF

Dense search understands paraphrase ("speed up the slow model" ↔ "make
inference faster") but misses rare literal tokens. Sparse BM25 nails exact
names, acronyms, and error codes but is blind to synonyms. Their score scales
are not comparable, so we fuse by **rank**:

```
RRF(chunk) = Σ over each list of  1 / (RRF_K + rank_in_that_list)
```

A chunk that ranks well in *either* retriever survives; ranking well in *both*
wins.

### Why a reranker

Chroma and BM25 are bi-encoders — query and document are processed separately,
so relevance is only approximated. A cross-encoder feeds `[query, chunk]`
through the model **together** and outputs one calibrated score. It is too slow
to run over the whole corpus, so it only runs on the ~40 fused candidates and
keeps the best 5. If even the best score is below `RERANK_SCORE_FLOOR`, **no**
document context is injected — an off-topic question shouldn't drag in random
passages.

### Short-term vs long-term memory

```
turn happens
  ├── ShortTermMemory.record()      every message → SQLite (verbatim)
  └── MemoryExtractor.extract()     LLM distils durable facts from the turn
            │
            ▼
      LongTermMemory.remember()     fact → SQLite row + Chroma vector
                                    (skipped if ~duplicate of an existing one)

next turn
  ├── ShortTermMemory.history()     last SHORT_TERM_WINDOW messages
  └── LongTermMemory.recall()       semantic search, then:
        1. drop any hit below LONG_TERM_MIN_SIMILARITY   (stale/irrelevant)
        2. rank the rest:
           score = 0.60·similarity + 0.20·importance
                 + 0.12·recency     + 0.08·frequency
```

Short-term memory is exact and cheap and disappears with the conversation.
Long-term memory is selective, persistent, and retrieved by meaning.

The similarity floor (step 1) is what stops Nexa injecting — and then reciting —
an unrelated old memory on every turn just because it was "important". Recalled
memories are also framed to the model as *silent background*: the system prompt
forbids "I remember…" / "you told me…" and any unprompted mention. Ask it
directly ("what do you know about me?") and it will summarise.

Recalled-memory vectors live in the `nexa_memories` Chroma collection. Nexa
forces that collection to **cosine** distance on startup; a collection left at
Chroma's default L2 (e.g. from an older build) is dropped and rebuilt from the
SQLite `memories` table, which is the source of truth.

---

## Project layout

```
nexa/
  config.py            all tunables (env-overridable)
  personality.py       system prompt
  models.py            plain data objects passed between layers
  providers/           LLMClient + EmbeddingModel (Ollama local + OpenAI-compatible cloud)
  storage/             StructuredStore + VectorStore (SQLite + Chroma impl)
  rag/                 chunking, loaders, sparse, reranker, retriever,
                       ingest, pipeline
  memory/              short_term, long_term, extractor, manager
  brain.py             Nexa class + build_nexa() composition root
  api/                 FastAPI app, routes, schemas
frontend/              voice-first UI: particle canvas + Web Speech + TTS (no build step)
scripts/               ingest_documents, inspect_store, manage_memory, reset
tests/                 pytest suite (uses fakes, no Ollama needed)
cli.py                 terminal REPL
run.py                 start the web app
documents/             drop your .txt / .md / .pdf here
```

---

## Setup

```bash
pip install -r requirements.txt

ollama pull nomic-embed-text        # embeddings - always local
ollama pull qwen3:4b               # only if you run the chat model locally too

cp .env.example .env               # optional; defaults work out of the box
```

### Chat model: local or hosted

Embeddings and the reranker always run locally. The **chat model** is chosen by
`LLM_BACKEND` in `.env`:

```ini
# local (default)
LLM_BACKEND=ollama
MODEL_NAME=qwen3:1.7b

# or a free hosted API (much faster - CPU-only local inference is slow)
LLM_BACKEND=groq
GROQ_API_KEY=gsk_...               # from console.groq.com, no card
MODEL_NAME=openai/gpt-oss-120b     # see GET https://api.groq.com/openai/v1/models
```

`groq`, `cerebras`, `openrouter`, `gemini`, `openai` all work through the same
`OpenAICompatibleLLM` — only the key and model id change. A hosted turn is
~2-4 s vs minutes for `qwen3:4b` on integrated graphics. Note: with a hosted
backend, the prompt (including retrieved documents + memories) leaves your
machine.

The reranker model (~90 MB ONNX) downloads automatically on first use and is
cached in `.fastembed_cache/`.

---

## Usage

### Terminal

```bash
python cli.py
```

- normal text → a streamed conversation turn
- `remember <something>` → store a long-term memory directly
- `exit` → quit

On startup it ingests everything in `documents/` and builds the BM25 index.

### Web app — voice-first

```bash
python run.py
# open http://127.0.0.1:8000  in Chrome or Edge
```

There is no text box. Nexa is drawn as a **particle constellation** that is
always listening. Say **“Nexa”** (or “Nex”) to wake it, then just talk. It
thinks, answers **out loud**, and its shape reacts through every state:

| state | look |
|---|---|
| idle | slow drifting sphere, cool blue — waiting for its name |
| wake | snaps inward, cyan shockwave |
| listening | shells pulse with your voice level (live, via Web Audio) |
| thinking | turbulent violet swarm |
| speaking | magenta jitter + a spark on every spoken word |

Controls (top-right): 🔊 mute Nexa's voice · ◍ show what it heard / the sources
and memories it used · ☾ send it back to sleep. Say “go to sleep” / “never
mind” to dismiss it. Talking while it speaks **interrupts** it.

Requires Chromium (Web Speech API) + a network connection for recognition.

### Bulk ingest / inspect / reset

```bash
python -m scripts.ingest_documents            # (re)ingest documents/
python -m scripts.ingest_documents ./notes    # a different folder or a file
python -m scripts.inspect_store --chunks --memories --documents
python -m scripts.manage_memory --list        # see everything Nexa "knows"
python -m scripts.manage_memory --forget <id> # delete one memory
python -m scripts.manage_memory --forget-all  # wipe long-term memory
python -m scripts.reset                        # wipe memory.db + chroma_db entirely
```

### Tests

```bash
pytest
```

---

## Swapping a backend

Each backend is one class behind an interface. To move off Chroma:

1. `class QdrantVectorStore(VectorStore)` in `nexa/storage/`.
2. Change the one line in `nexa/brain.py:build_nexa()` that constructs the
   vector store.

Nothing in `rag/`, `memory/`, or `brain.py` changes — they only know the
interface. The same pattern applies to `SQLiteStore → PostgresStore`,
`OllamaLLM → OpenAILLM`, `BM25Retriever → SpladeRetriever`.

---

## Config reference

See `.env.example`. The knobs you'll touch most:

| Setting | Default | Effect |
|---|---|---|
| `MODEL_NAME` | `qwen3:4b` | chat model; `qwen3:1.7b` is much faster on CPU |
| `BREAKPOINT_PERCENTILE` | `95` | lower → more, smaller chunks |
| `FINAL_CONTEXT_N` | `5` | how many chunks reach the prompt |
| `RERANK_SCORE_FLOOR` | `0.0` | raise to be stricter about injecting context |
| `SHORT_TERM_WINDOW` | `12` | recent messages kept as working memory |
| `MEMORY_EXTRACTION` | `true` | set `false` to skip the extra LLM call per turn |

---

## Notes and limits

- **CPU inference is slow.** Memory extraction adds one extra LLM call per turn;
  it runs *after* the reply is shown. Set `MEMORY_EXTRACTION=false` to disable.
- **Qwen3 always reasons.** With `LLM_THINK=true` (default) Ollama returns that
  reasoning in a separate field and Nexa drops it, so `content` stays clean —
  but the model still spends CPU time thinking. `qwen3:1.7b` roughly halves it.
- **BM25 index is in-memory**, rebuilt on startup and after each upload. Fine for
  a personal corpus; revisit at thousands of documents.
- **Web Speech API** only works in Chromium browsers and needs a network
  connection; the UI falls back to text-only elsewhere.
- If you have a `chroma_db/` from Nexa v1, its `nexa_memories` collection was
  created with L2 distance. It keeps working, but for clean cosine scores you
  can delete `chroma_db/` and `memory.db` and start fresh.
