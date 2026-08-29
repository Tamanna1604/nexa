"""MemoryExtractor parses the LLM's JSON defensively."""

from __future__ import annotations

from nexa.memory.extractor import MemoryExtractor
from tests.conftest import ScriptedLLM


def test_parses_clean_json_array():
    llm = ScriptedLLM(
        ['[{"text": "User has a sister named Anchal.", "type": "relationship", "importance": 7}]']
    )
    facts = MemoryExtractor(llm).extract("my sister is anchal", "noted")
    assert facts == [
        {"text": "User has a sister named Anchal.", "type": "relationship", "importance": 7}
    ]


def test_pulls_json_out_of_prose_and_fences():
    llm = ScriptedLLM(
        ['Sure! Here you go:\n```json\n[{"text": "User likes tea.", "type": "preference"}]\n```']
    )
    facts = MemoryExtractor(llm).extract("i like tea", "ok")
    assert facts[0]["text"] == "User likes tea."
    assert facts[0]["importance"] == 5  # default when missing


def test_malformed_json_yields_empty():
    for bad in ["not json at all", "[{broken}", "{}", ""]:
        assert MemoryExtractor(ScriptedLLM([bad])).extract("x", "y") == []


def test_importance_is_clamped():
    llm = ScriptedLLM(['[{"text": "big deal", "type": "fact", "importance": 99}]'])
    assert MemoryExtractor(llm).extract("x", "y")[0]["importance"] == 10
