"""SemanticChunker should break where the topic shifts, not mid-sentence."""

from __future__ import annotations

from nexa.providers.base import EmbeddingModel
from nexa.rag.chunking import SemanticChunker, split_sentences


class TopicEmbedder(EmbeddingModel):
    """Vector points along a different axis per topic keyword."""

    TOPICS = ["cat", "rocket", "bread"]

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            low = text.lower()
            vec = [1.0 if topic in low else 0.0 for topic in self.TOPICS]
            if not any(vec):
                vec = [0.01, 0.01, 0.01]
            out.append(vec)
        return out


def test_split_sentences_basic():
    assert split_sentences("Hello world. How are you?\n\nFine.") == [
        "Hello world.",
        "How are you?",
        "Fine.",
    ]


def test_breaks_at_topic_shift():
    text = (
        "The cat slept. The cat purred. The cat is soft. "
        "The rocket launched. The rocket reached orbit. The rocket is fast."
    )
    chunker = SemanticChunker(
        TopicEmbedder(), percentile=80, context_window=0, min_sentences=1, max_chars=10_000
    )
    chunks = chunker.split(text)

    assert len(chunks) == 2
    assert "cat" in chunks[0] and "rocket" not in chunks[0]
    assert "rocket" in chunks[1] and "cat" not in chunks[1]


def test_short_text_is_one_chunk():
    chunker = SemanticChunker(TopicEmbedder(), min_sentences=2)
    assert chunker.split("Just one sentence here.") == ["Just one sentence here."]


def test_max_chars_hard_split():
    long_sentence_doc = ". ".join(f"sentence number {i} about bread" for i in range(40)) + "."
    chunker = SemanticChunker(
        TopicEmbedder(), percentile=99, context_window=0, min_sentences=1, max_chars=120
    )
    chunks = chunker.split(long_sentence_doc)
    assert all(len(c) <= 120 + 40 for c in chunks)  # +slack for the trailing sentence
    assert len(chunks) > 1
