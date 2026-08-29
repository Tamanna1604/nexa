# Notes on Retrieval-Augmented Generation

## The problem RAG solves

A language model only knows what was in its training data. RAG lets it answer
questions about private or fresh information by fetching relevant text at query
time and putting it in the prompt. The model then grounds its answer in that
retrieved text instead of guessing from parameters alone.

## Chunking

Documents are too long to embed as a single vector, so they are split into
chunks. Fixed-size chunking (every 500 tokens) is simple but cuts sentences and
mixes topics. Semantic chunking measures the embedding distance between
consecutive sentences and starts a new chunk wherever the topic shifts, so each
chunk stays about one idea.

## Dense retrieval

Dense retrieval embeds the query and every chunk into the same vector space and
returns the chunks whose vectors are closest, usually by cosine similarity. It
captures meaning, so "car" matches "automobile", but it can miss exact strings
like product codes or rare proper nouns.

## Sparse retrieval and BM25

Sparse retrieval scores documents by term overlap. BM25 is the standard
algorithm: it rewards query terms that appear often in a document, discounts
terms that appear in many documents (inverse document frequency), and
normalises for document length so long documents do not dominate. BM25 is
excellent at exact keyword matching and needs no training.

## Reciprocal Rank Fusion

When you run dense and sparse retrieval together you get two ranked lists with
incomparable score scales. Reciprocal Rank Fusion combines them using only rank
position: each document scores the sum over lists of one divided by a constant
k plus its rank. Documents that rank well in either list rise to the top.

## Cross-encoder reranking

A bi-encoder embeds query and document separately, so it only approximates
their relationship. A cross-encoder concatenates the query and a candidate
document and runs them through a transformer together, producing a single
accurate relevance score. It is expensive, so it is applied only to the few
dozen candidates that fusion already shortlisted.
