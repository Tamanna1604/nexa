"""Reciprocal Rank Fusion ordering."""

from __future__ import annotations

from nexa.rag.retriever import reciprocal_rank_fusion


def test_item_in_both_lists_wins():
    dense = ["a", "b", "c"]
    sparse = ["b", "d", "a"]
    fused = reciprocal_rank_fusion([dense, sparse], k=60)
    order = [item for item, _ in fused]
    # "a" (ranks 1 & 3) and "b" (ranks 2 & 1) appear twice -> ahead of singletons.
    assert set(order[:2]) == {"a", "b"}
    assert order[0] == "b"  # 1/61 + 1/62  >  1/61 + 1/63
    assert set(order[2:]) == {"c", "d"}


def test_single_list_preserves_order():
    fused = reciprocal_rank_fusion([["x", "y", "z"]], k=60)
    assert [item for item, _ in fused] == ["x", "y", "z"]


def test_empty_input():
    assert reciprocal_rank_fusion([], k=60) == []
    assert reciprocal_rank_fusion([[], []], k=60) == []
