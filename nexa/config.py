"""Central configuration.

Every tunable number in Nexa lives here so experiments are one edit away.
Values can be overridden with environment variables or a `.env` file
(e.g. `MODEL_NAME=qwen3:1.7b` in `.env` to run the faster model).
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root = the folder that contains this package.
ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- Identity -------------------------------------------------------
    SYSTEM_NAME: str = "Nexa"

    # ---- Chat model backend ----------------------------------------
    # Where the conversational LLM runs:
    #   "ollama"   - local (default)
    #   "groq" | "cerebras" | "openrouter" | "gemini" | "openai"
    #              - a hosted, OpenAI-compatible API (needs LLM_API_KEY)
    LLM_BACKEND: str = "ollama"
    # The model id for that backend, e.g. "qwen3:4b" (ollama) or
    # "llama-3.3-70b-versatile" (groq).
    MODEL_NAME: str = "qwen3:4b"

    # API key for the hosted backend. GROQ_API_KEY / CEREBRAS_API_KEY / etc. are
    # also accepted (see _resolved_api_key in the OpenAI-compatible provider).
    LLM_API_KEY: str | None = None
    GROQ_API_KEY: str | None = None
    CEREBRAS_API_KEY: str | None = None
    OPENROUTER_API_KEY: str | None = None
    GEMINI_API_KEY: str | None = None
    OPENAI_API_KEY: str | None = None
    # Override the base URL if you use a provider not in the table above.
    LLM_BASE_URL: str | None = None
    # Optional: run memory extraction + reconciliation on a DIFFERENT (cheaper)
    # model. On Groq the token/min limit is per-model, so a second model doubles
    # your effective budget. Blank = reuse MODEL_NAME.
    EXTRACTOR_MODEL: str | None = None

    # ---- Local models (always used for embeddings + reranking) --------
    # Ollama embedding model - used for BOTH memory and RAG chunk vectors.
    EMBEDDING_MODEL: str = "nomic-embed-text"
    # Cross-encoder reranker (fastembed / ONNX - no PyTorch).
    RERANKER_MODEL: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    # Optional custom Ollama host, e.g. "http://localhost:11434".
    OLLAMA_HOST: str | None = None
    # Qwen3 is a "thinking" model. With think=true, Ollama returns the reasoning
    # in a separate `thinking` field and keeps `content` clean - so we ask for it
    # and simply don't surface the thinking. (Set false for non-thinking models;
    # any leaked <think>...</think> is stripped defensively.)
    LLM_THINK: bool = True
    # Hard cap on generated tokens (keeps a runaway answer from hanging the CPU).
    LLM_NUM_PREDICT: int = 1200
    # Sampling temperature passed to Ollama.
    LLM_TEMPERATURE: float = 0.7

    # ---- Storage paths --------------------------------------------------
    # Kept at the historical locations so existing data keeps working.
    DB_PATH: str = str(ROOT / "memory.db")
    CHROMA_PATH: str = str(ROOT / "chroma_db")
    DOCUMENTS_DIR: str = str(ROOT / "documents")

    # Chroma collection names.
    MEMORY_COLLECTION: str = "nexa_memories"
    CHUNK_COLLECTION: str = "nexa_chunks"

    # ---- Semantic chunking -------------------------------------------
    # A sentence boundary becomes a chunk boundary when the semantic
    # distance to the next sentence is above this percentile of all
    # distances in the document.
    BREAKPOINT_PERCENTILE: int = 95
    # Combine this many neighbours on each side before embedding, to make
    # the distance signal less noisy (0 = embed each sentence alone).
    CHUNK_CONTEXT_WINDOW: int = 1
    MIN_CHUNK_SENTENCES: int = 2
    MAX_CHUNK_CHARS: int = 1200

    # ---- Hybrid retrieval + rerank -----------------------------------
    DENSE_TOP_K: int = 20          # candidates from the vector store
    SPARSE_TOP_K: int = 20         # candidates from BM25
    RRF_K: int = 60               # Reciprocal Rank Fusion constant
    RERANK_CANDIDATES: int = 40    # fused list size handed to the reranker
    FINAL_CONTEXT_N: int = 5       # chunks actually injected into the prompt
    # Cross-encoder logit below which a chunk is NOT injected. ms-marco-MiniLM
    # puts genuinely relevant passages at ~2-8 and off-topic ones below 0, so a
    # floor around 2 keeps unrelated documents out of the prompt (a big cause of
    # "it answered with something irrelevant").
    RERANK_SCORE_FLOOR: float = 2.0

    # ---- Memory ------------------------------------------------------
    SHORT_TERM_WINDOW: int = 8     # recent messages kept as working memory
    LONG_TERM_TOP_K: int = 5       # long-term memories recalled per turn
    # A recalled memory is only shown to the model when its RAW cosine similarity
    # to the current message clears this. Stops stale, unrelated memories from
    # being injected - and recited - every single turn. (nomic-embed-text puts
    # genuine matches around 0.6-0.9 and unrelated text around 0.3-0.45.)
    LONG_TERM_MIN_SIMILARITY: float = 0.5
    # Skip storing an extracted fact if it is this cosine-similar to one we
    # already hold. Lower = catches more paraphrase duplicates ("reading Dear
    # Baby" vs "reading the book Dear Baby") at some risk of merging two
    # genuinely different facts.
    MEMORY_DEDUPE_THRESHOLD: float = 0.87
    # Turn the (expensive) LLM extraction pass on/off.
    MEMORY_EXTRACTION: bool = True

    # ---- Tools (live data / actions the LLM can call) ---------------
    TOOLS_ENABLED: bool = True
    TOOL_MAX_ITERS: int = 4           # cap on tool-call rounds per turn
    # Local timezone, e.g. "Asia/Kolkata". Blank = the machine's local zone.
    TIMEZONE: str | None = None
    # Used by get_weather when the user doesn't name a place.
    DEFAULT_LOCATION: str = "Pune"
    # Let the assistant launch apps on this machine (open_app tool). Also gates
    # the whatsapp tool and the `watch` tool (opens Netflix/Prime/Hotstar).
    ALLOW_APP_LAUNCH: bool = True
    # The web_search tool - top results from DuckDuckGo as text (keyless).
    WEB_SEARCH_ENABLED: bool = True
    # Let the `watch` tool actually click through to playback via Playwright
    # (pip install playwright && playwright install chromium). Off = it just
    # opens the service's search page in your browser.
    BROWSER_AUTOMATION: bool = False
    # Drive your REAL, logged-in Chrome for the `watch` tool. Chrome allows one
    # process per profile, so if Chrome is already running Nexa closes it,
    # reopens it with a debugging port (your tabs restore), then attaches.
    # Set False to use the isolated throwaway profile in BROWSER_PROFILE_DIR
    # instead (you log into Netflix/Prime/Hotstar once in that window).
    CHROME_USE_REAL_PROFILE: bool = True
    # Chrome's "User Data" folder. Blank = auto-detect the OS default.
    CHROME_USER_DATA_DIR: str = ""
    # Which Chrome profile inside it holds your Netflix login: "Default",
    # "Profile 1", ... See chrome://version -> "Profile Path" (last segment).
    CHROME_PROFILE_DIRECTORY: str = "Default"
    # Isolated profile dir, used only when CHROME_USE_REAL_PROFILE=False.
    BROWSER_PROFILE_DIR: str = str(ROOT / ".nexa_browser")
    # Which Netflix "Who's watching?" profile to pick before playing. Blank =
    # take whatever profile is already active / the first one.
    NETFLIX_PROFILE: str = "Tamzy"
    # Extra "app name" -> launch target, e.g. {"outlook": "outlookmail:"}.
    # Set as JSON in .env:  EXTRA_APP_ALIASES='{"figma": "figma:"}'
    EXTRA_APP_ALIASES: dict[str, str] = {}
    # name -> phone book for the whatsapp tool (WhatsApp's own contacts can't be read)
    CONTACTS_FILE: str = str(ROOT / "contacts.json")
    # allow driving app windows with the mouse/keyboard (whatsapp call button,
    # whatsapp action='send' pressing Enter). off by default - it's fragile and
    # takes over focus. needs `pip install pywinauto`.
    ALLOW_UI_AUTOMATION: bool = False
    # seconds to wait for the WhatsApp desktop window before pressing send
    # (fallback path only; WhatsApp Web is used when BROWSER_AUTOMATION=true).
    WHATSAPP_SEND_DELAY: float = 4.0

    # ---- Gmail (read-only, via IMAP) --------------------------------
    # An App Password from myaccount.google.com/apppasswords (needs 2FA on).
    # Both set -> the `gmail` tool is available.
    GMAIL_ADDRESS: str = ""
    GMAIL_APP_PASSWORD: str = ""

    # ---- API -------------------------------------------------------
    API_HOST: str = "127.0.0.1"
    API_PORT: int = 8000

    # ---- Debug -------------------------------------------------------
    # Print the exact prompt (personality + memory block + doc context +
    # history + user turn) to the terminal before every LLM call.
    DEBUG_PROMPT: bool = False


settings = Settings()
