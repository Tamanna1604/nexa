"""Nexa's brain: assemble context from memory + RAG, then talk to the LLM.

This module is the ONLY place that knows which concrete implementations are in
use. `build_nexa()` wires them together; `Nexa` itself depends only on the
interfaces, so swapping Ollama/SQLite/Chroma is a change here and nowhere else.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Iterator

from nexa.config import settings
from nexa.memory import (
    LongTermMemory,
    MemoryExtractor,
    MemoryManager,
    MemoryReconciler,
    ShortTermMemory,
)
from nexa.models import Chunk, Memory
from nexa.personality import PERSONALITY
from nexa.providers import EmbeddingModel, LLMClient, OllamaEmbeddings, OllamaLLM
from nexa.providers.base import Message
from nexa.rag import (
    BM25Retriever,
    FastEmbedReranker,
    HybridRetriever,
    IngestionPipeline,
    RAGPipeline,
    SemanticChunker,
)
from nexa.storage import ChromaVectorStore, SQLiteStore
from nexa.storage.base import StructuredStore, VectorStore
from nexa.tools import (
    ClockTool,
    GmailTool,
    OpenAppTool,
    StreamingTool,
    ToolRegistry,
    WeatherTool,
    WebSearchTool,
    WhatsAppTool,
    current_time_string,
)


@dataclass
class RespondResult:
    conversation_id: str
    reply: str
    sources: list[Chunk] = field(default_factory=list)
    memories_recalled: list[Memory] = field(default_factory=list)
    memories_stored: list[Memory] = field(default_factory=list)
    memories_forgotten: list[Memory] = field(default_factory=list)


class Nexa:
    
    def __init__(
        self,
        llm: LLMClient,
        memory: MemoryManager,
        rag: RAGPipeline,
        store: StructuredStore,
        *,
        tools: ToolRegistry | None = None,
        personality: str = PERSONALITY,
    ) -> None:
        self.llm = llm
        self.memory = memory
        self.rag = rag
        self.store = store
        self.tools = tools
        self.personality = personality

    @property
    def _tools_active(self) -> bool:
        return bool(self.tools) and hasattr(self.llm, "chat_raw")

    # ------------------------------------------------------------------
    def start_conversation(self, title: str = "") -> str:
        return self.store.create_conversation(title)

    def _ensure_conversation(self, conversation_id: str | None) -> str:
        if conversation_id and self.store.conversation_exists(conversation_id):
            return conversation_id
        return self.store.create_conversation()

    # ------------------------------------------------------------------
    def _assemble(self, user_message: str, conversation_id: str):
        """Gather context and build the message list. Records the user turn."""
        # Greetings / one-word replies don't need document retrieval or a memory
        # search - skipping them shaves the reranker + a couple of embedding
        # calls off every "hi".
        trivial = _is_smalltalk(user_message)
        mem_ctx = self.memory.context_for(
            user_message, conversation_id, recall_long_term=not trivial
        )
        chunks = [] if trivial else self.rag.retrieve(user_message)
        self.memory.record_user(conversation_id, user_message)

        messages: list[Message] = [
            {"role": "system", "content": self.personality},
            {"role": "system", "content": f"Right now it is {current_time_string(settings.TIMEZONE)}."},
        ]

        memory_block = mem_ctx.long_term_block()
        if memory_block:
            messages.append({"role": "system", "content": memory_block})

        context_block = self.rag.build_context(chunks)
        if context_block:
            messages.append({"role": "system", "content": context_block})

        messages.extend(mem_ctx.short_term)
        messages.append({"role": "user", "content": user_message})

        if settings.DEBUG_PROMPT:
            _dump_prompt(messages, mem_ctx, chunks)
        return messages, mem_ctx, chunks

    def _finish(self, conversation_id: str, user_message: str, reply: str):
        self.memory.record_assistant(conversation_id, reply)
        return self.memory.consolidate(user_message, reply, conversation_id)

    def _use_tools_for(self, user_message: str) -> bool:
        """Only pay the (multi-call, tool-spec) tool loop when the message
        plausibly needs live data. Most turns don't."""
        return self._tools_active and bool(_TOOL_HINT.search(user_message))

    def _generate(self, messages: list[Message], user_message: str) -> str:
        """Produce the reply text, running the tool-call loop only when needed."""
        if not self._use_tools_for(user_message):
            debug("FINAL PROMPT SENT TO MODEL (no tools)", messages)
            return self.llm.chat(messages)

        specs = self.tools.specs()
        convo = list(messages)
        # small hosted models sometimes "refuse" instead of searching; when the
        # ask is unambiguously a lookup, make the first round call web_search.
        force_first = (
            _FORCE_WEB.search(user_message)
            and any(s["function"]["name"] == "web_search" for s in specs)
        )
        for i in range(settings.TOOL_MAX_ITERS):
            debug(f"PROMPT SENT TO MODEL (tool round {i + 1}, {len(convo)} msgs)", convo)
            choice = (
                {"type": "function", "function": {"name": "web_search"}}
                if i == 0 and force_first
                else None
            )
            try:
                resp = self.llm.chat_raw(convo, tools=specs, tool_choice=choice)
            except RuntimeError as exc:
                # forcing a tool call can 400 if the model answers directly
                # anyway (small hosted models do this). Recover, don't crash.
                if choice is None or "tool_use_failed" not in str(exc):
                    raise
                direct = _failed_generation(str(exc))
                if direct and "did not call a tool" in str(exc):
                    return direct
                resp = self.llm.chat_raw(convo, tools=specs)  # retry, unforced
            calls = resp.get("tool_calls") or []
            if not calls:
                debug("TOOL-LOOP: final answer", resp.get("content") or "")
                return resp.get("content") or ""
            convo.append(
                {"role": "assistant", "content": resp.get("content") or "", "tool_calls": calls}
            )
            for call in calls:
                fn = call.get("function", {})
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                out = self.tools.run(fn.get("name", ""), args)
                debug(f"TOOL CALL (round {i + 1}): {fn.get('name')}({args})", out)
                convo.append(
                    {"role": "tool", "tool_call_id": call.get("id", ""), "content": out}
                )
        # hit the iteration cap - force a plain answer from what we've gathered
        return self._force_plain_answer(convo)

    def _force_plain_answer(self, convo: list[Message]) -> str:
        """Last resort when the tool loop won't converge. Some hosted models
        (Groq gpt-oss) return HTTP 400 - "tool choice is none, but model called
        a tool" - if the request carries tool-call history but no `tools`. So we
        flatten the tool scaffolding into plain text and ask once more, plainly."""
        flat: list[Message] = []
        for m in convo:
            role = m.get("role")
            if role == "tool":
                flat.append(
                    {"role": "system", "content": f"[tool result] {m.get('content', '')}"}
                )
            elif role == "assistant" and m.get("tool_calls"):
                if m.get("content"):
                    flat.append({"role": "assistant", "content": m["content"]})
            else:
                flat.append(m)
        flat.append(
            {
                "role": "system",
                "content": (
                    "Answer the user now, in plain text, using the tool results "
                    "above. Do not call any tools."
                ),
            }
        )
        try:
            return self.llm.chat(flat)
        except Exception as exc:  # noqa: BLE001
            debug("FORCE-PLAIN-ANSWER failed", str(exc))
            return (
                "I pulled some information but couldn't put the reply together. "
                "Try asking again, a little more specifically."
            )

    # ------------------------------------------------------------------
    def respond(self, user_message: str, conversation_id: str | None = None) -> RespondResult:
        conversation_id = self._ensure_conversation(conversation_id)
        messages, mem_ctx, chunks = self._assemble(user_message, conversation_id)
        reply = self._generate(messages, user_message)
        debug("REPLY from chat model", reply)
        cons = self._finish(conversation_id, user_message, reply)
        return RespondResult(
            conversation_id=conversation_id,
            reply=reply,
            sources=chunks,
            memories_recalled=mem_ctx.long_term,
            memories_stored=cons.stored,
            memories_forgotten=cons.forgotten,
        )

    def respond_stream(
        self, user_message: str, conversation_id: str | None = None
    ) -> Iterator[dict]:
        """Yield {'type': 'token', 'text': ...} events, then one 'meta', then 'done'."""
        conversation_id = self._ensure_conversation(conversation_id)
        messages, mem_ctx, chunks = self._assemble(user_message, conversation_id)

        if self._use_tools_for(user_message):
            # tool loop needs full (non-streamed) turns and a tool (WhatsApp Web,
            # a browser drive) can take a minute. Run it off-thread and emit a
            # keepalive every few seconds so the client doesn't abandon the turn.
            import threading

            box: dict[str, str] = {}
            worker = threading.Thread(
                target=lambda: box.__setitem__("reply", self._generate(messages, user_message)),
                daemon=True,
            )
            worker.start()
            while worker.is_alive():
                worker.join(timeout=4)
                if worker.is_alive():
                    yield {"type": "status", "text": "working"}
            reply = box.get("reply", "")
            for piece in re.findall(r"\S+\s*", reply):
                yield {"type": "token", "text": piece}
        else:
            parts: list[str] = []
            for token in self.llm.stream_chat(messages):
                parts.append(token)
                yield {"type": "token", "text": token}
            reply = "".join(parts)

        debug("REPLY from chat model", reply)

        # tell the UI the spoken answer is complete BEFORE the (possibly slow,
        # rate-limited) memory bookkeeping - so the voice loop returns to
        # listening immediately instead of waiting on extraction
        self.memory.record_assistant(conversation_id, reply)
        yield {
            "type": "meta",
            "conversation_id": conversation_id,
            "sources": [_chunk_view(c) for c in chunks],
            "memories_recalled": [_memory_view(m) for m in mem_ctx.long_term],
        }
        yield {"type": "done"}

        cons = self.memory.consolidate(user_message, reply, conversation_id)
        yield {
            "type": "memory",
            "memories_stored": [_memory_view(m) for m in cons.stored],
            "memories_forgotten": [_memory_view(m) for m in cons.forgotten],
        }


# ----------------------------------------------------------------------
# view helpers (plain dicts for JSON / the frontend panels)
# ----------------------------------------------------------------------
_SMALLTALK = re.compile(
    r"^\W*(hi|hey+|hello|yo|sup|hiya|howdy|"
    r"thanks|thank you|thx|ty|"
    r"ok|okay|kk|cool|nice|great|awesome|good|"
    r"good morning|good afternoon|good evening|good night|gn|"
    r"bye|goodbye|see ya|cya|later|"
    r"yes|no|yeah|nah|yep|nope|nvm|never mind|"
    r"test|testing|hello nexa|hey nexa)\W*$",
    re.IGNORECASE,
)


def _is_smalltalk(text: str) -> bool:
    t = text.strip()
    return bool(_SMALLTALK.match(t)) or len(t.split()) <= 1


# messages that plausibly need a tool (clock / weather / open an app)
_TOOL_HINT = re.compile(
    r"\b(time|clock|hour|minute|o'?clock|date|day|today|tonight|tomorrow|yesterday|"
    r"morning|afternoon|evening|week(day|end)?|month|year|schedule|when|"
    r"weather|temperature|forecast|rain|raining|sunny|cloudy|snow|humid|"
    r"hot|cold|windy|degrees?|celsius|fahrenheit|"
    r"open|launch|start up|fire up|bring up|pull up|"
    r"whatsapp|call|ring|dial|message|text|msg|unread|reply|chat|chats|"
    r"e-?mail|gmail|inbox|mail|"
    r"search|google|look up|lookup|browse|web|news|price|"
    r"mean|meaning|define|definition|explain|what is|what's|whats|"
    r"who is|tell me about|latest|current|"
    r"netflix|prime video|hotstar|jiohotstar|disney|youtube|"
    r"watch|stream|streaming|series|episode|binge|play)\b",
    re.IGNORECASE,
)


def _failed_generation(err_text: str) -> str:
    """Pull the model's text out of a Groq `tool_use_failed` 400 body."""
    m = re.search(r'"failed_generation"\s*:\s*"((?:[^"\\]|\\.)*)"', err_text)
    if not m:
        return ""
    try:
        return json.loads(f'"{m.group(1)}"').strip()
    except (json.JSONDecodeError, ValueError):
        return m.group(1).strip()


# an ask that is unambiguously "go look this up on the web"
_FORCE_WEB = re.compile(
    r"\b(news|headlines?|breaking|current events|"
    r"meaning of|what does .+ mean|define|definition of|"
    r"search (for|up|google)|look (this |it )?up|google (it|this|for))\b",
    re.IGNORECASE,
)


def debug(label: str, body) -> None:
    """Print a labelled block when DEBUG_PROMPT=true. Used across brain + memory."""
    if not settings.DEBUG_PROMPT:
        return
    print("\n" + "-" * 70)
    print(f">>> {label}")
    print("-" * 70)
    if isinstance(body, (list, tuple)):
        for m in body:
            if isinstance(m, dict) and "role" in m:
                print(f"\n[{m['role'].upper()}]")
                if m.get("content"):
                    print(m["content"])
                if m.get("tool_calls"):
                    print(f"(tool_calls: {json.dumps(m['tool_calls'])})")
            else:
                print(m)
    else:
        print(body)
    print("-" * 70 + "\n")


def _dump_prompt(messages: list[Message], mem_ctx, chunks) -> None:
    """Print the exact prompt sent to the LLM (DEBUG_PROMPT=true)."""
    debug(
        f"PROMPT to chat model  ({len(mem_ctx.long_term)} memories, {len(chunks)} doc chunks)",
        messages,
    )


def _chunk_view(c: Chunk) -> dict:
    return {
        "title": c.title or "document",
        "text": c.text[:600],
        "score": round(c.score, 4),
    }


def _memory_view(m: Memory) -> dict:
    return {
        "text": m.text,
        "type": m.memory_type,
        "importance": m.importance,
        "score": round(m.score, 4),
    }


# ----------------------------------------------------------------------
# composition root
# ----------------------------------------------------------------------
@dataclass
class NexaBundle:
    nexa: Nexa
    store: StructuredStore
    vectors: VectorStore
    embedder: EmbeddingModel
    sparse: BM25Retriever
    ingestion: IngestionPipeline

    def bootstrap(self, *, ingest: bool = True) -> None:
        """Create tables, heal the memory index, ingest docs, build BM25."""
        self.store.setup()
        self.nexa.memory.long_term.ensure_index()
        if ingest:
            self.ingestion.ingest_directory()
        self.sparse.rebuild(self.store.all_chunks())


def build_llm(model: str | None = None) -> LLMClient:
    """Pick the chat model backend from LLM_BACKEND (default: local Ollama)."""
    backend = (settings.LLM_BACKEND or "ollama").lower()
    if backend == "ollama":
        return OllamaLLM(model=model)
    from nexa.providers import OpenAICompatibleLLM

    return OpenAICompatibleLLM(backend=backend, model=model)


def build_nexa() -> NexaBundle:
    store: StructuredStore = SQLiteStore(settings.DB_PATH)
    vectors: VectorStore = ChromaVectorStore(settings.CHROMA_PATH)
    embedder: EmbeddingModel = OllamaEmbeddings()   # embeddings stay local
    llm: LLMClient = build_llm()
    print(f"[nexa] chat backend: {settings.LLM_BACKEND} ({settings.MODEL_NAME})")

    # memory extraction / reconciliation can run on a separate (cheaper) model -
    # on Groq the rate limit is per-model, so this roughly doubles throughput
    if settings.EXTRACTOR_MODEL:
        mem_llm: LLMClient = build_llm(model=settings.EXTRACTOR_MODEL)
        print(f"[nexa] memory model: {settings.EXTRACTOR_MODEL}")
    else:
        mem_llm = llm

    # memory
    short_term = ShortTermMemory(store)
    long_term = LongTermMemory(store, vectors, embedder)
    extractor = MemoryExtractor(mem_llm)
    reconciler = MemoryReconciler(mem_llm)
    memory = MemoryManager(short_term, long_term, extractor, reconciler)

    # rag
    chunker = SemanticChunker(embedder)
    sparse = BM25Retriever()
    hybrid = HybridRetriever(store, vectors, embedder, sparse)
    reranker = FastEmbedReranker()
    rag = RAGPipeline(hybrid, reranker)
    ingestion = IngestionPipeline(store, vectors, embedder, chunker)

    # tools (live data + actions the LLM can call)
    tools = None
    if settings.TOOLS_ENABLED:
        tool_list = [ClockTool(settings.TIMEZONE), WeatherTool(settings.DEFAULT_LOCATION)]
        if settings.WEB_SEARCH_ENABLED:
            tool_list.append(WebSearchTool())
        if settings.ALLOW_APP_LAUNCH:
            tool_list.append(OpenAppTool())
            tool_list.append(WhatsAppTool())
            tool_list.append(StreamingTool())
        if settings.GMAIL_ADDRESS and settings.GMAIL_APP_PASSWORD:
            tool_list.append(GmailTool())
        tools = ToolRegistry(tool_list)

    nexa = Nexa(llm, memory, rag, store, tools=tools)
    if tools and not nexa._tools_active:
        print("[nexa] tools defined but the current LLM backend can't call them (use groq/openai).")
    elif tools:
        print(f"[nexa] tools: {', '.join(tools.names())}")
    return NexaBundle(nexa, store, vectors, embedder, sparse, ingestion)
