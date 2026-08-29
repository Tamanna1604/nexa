# Project Nexa

Nexa is a personal AI assistant built from scratch as a long-term learning
project. The goal is not to wrap a hosted chatbot API, but to understand and
build the architecture around a language model.

## Local inference

Nexa runs its language model locally with Ollama. The current chat model is
Qwen3. Because the development laptop only has Intel UHD integrated graphics,
Ollama runs entirely on the CPU, which makes the 4B model slow. Options to
speed it up include the smaller Qwen3 1.7B model, response streaming, or an
external GPU.

## Memory

Nexa keeps two kinds of memory. Structured memory lives in SQLite and holds
conversations, messages, and extracted facts. Semantic memory lives in
ChromaDB as vector embeddings, so past information can be retrieved by meaning
rather than exact wording. Embeddings are produced by the nomic-embed-text
model.

## Retrieval

The retrieval system uses hybrid search. A dense vector search finds passages
that are semantically similar to the question, and a sparse BM25 search finds
passages that share exact keywords. The two result lists are combined with
Reciprocal Rank Fusion, and a cross-encoder reranker then reorders the merged
list so the most relevant passages end up in the prompt.

## Roadmap

Future versions of Nexa should add tool use and function calling, speech
input and output, computer vision, and eventually agentic planning that can
carry out multi-step tasks without supervision.
