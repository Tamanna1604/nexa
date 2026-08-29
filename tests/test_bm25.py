"""BM25 sparse retrieval picks the chunk that shares rare keywords."""

from __future__ import annotations

from nexa.models import Chunk
from nexa.rag.sparse import BM25Retriever, tokenize


def _chunk(cid: str, text: str) -> Chunk:
    return Chunk(id=cid, document_id="d", ordinal=0, text=text)


def test_tokenize_drops_stopwords():
    assert tokenize("The quick brown FOX") == ["quick", "brown", "fox"]


def test_keyword_match_ranks_first():
    corpus = [
        _chunk("1", "photosynthesis converts sunlight into chemical energy in plants"),
        _chunk("2", "the mitochondria is the powerhouse of the cell"),
        _chunk("3", "a recipe for sourdough bread needs flour water and salt"),
    ]
    bm25 = BM25Retriever()
    bm25.rebuild(corpus)

    results = bm25.search("how does photosynthesis work", top_k=3)
    assert results
    assert results[0][0] == "1"


def test_empty_index_returns_nothing():
    bm25 = BM25Retriever()
    bm25.rebuild([])
    assert bm25.search("anything", top_k=5) == []
