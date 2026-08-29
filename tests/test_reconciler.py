"""MemoryReconciler: decides delete / update / keep for related memories."""

from __future__ import annotations

from nexa.memory.reconciler import MemoryChange, MemoryReconciler
from nexa.models import Memory
from tests.conftest import ScriptedLLM


def _mem(mid: str, text: str) -> Memory:
    return Memory(id=mid, text=text, memory_type="fact", importance=5, created_at="")


def test_delete_on_correction():
    related = [_mem("a1", "User's brother is named Karan."), _mem("a2", "User has a brother.")]
    rec = MemoryReconciler(ScriptedLLM(['[{"id": "a1", "action": "delete"}]']))
    changes = rec.review("his name is Ravi not Karan", "ok", related)
    assert changes == [MemoryChange(id="a1", action="delete")]


def test_update_keeps_the_name_on_a_breakup():
    related = [_mem("a1", "User has a boyfriend named Rohan.")]
    rec = MemoryReconciler(
        ScriptedLLM(['[{"id": "a1", "action": "update", "text": "Rohan is the user\'s ex-boyfriend."}]'])
    )
    changes = rec.review("we broke up", "sorry to hear that", related)
    assert changes[0].action == "update"
    assert changes[0].text == "Rohan is the user's ex-boyfriend."


def test_ignores_ids_not_in_candidate_set_and_bad_actions():
    related = [_mem("a1", "x")]
    rec = MemoryReconciler(
        ScriptedLLM(['[{"id":"a1","action":"delete"},{"id":"zzz","action":"delete"},{"id":"a1","action":"frobnicate"}]'])
    )
    assert rec.review("u", "a", related) == [MemoryChange(id="a1", action="delete")]


def test_update_without_text_is_dropped():
    related = [_mem("a1", "x")]
    rec = MemoryReconciler(ScriptedLLM(['[{"id": "a1", "action": "update"}]']))
    assert rec.review("u", "a", related) == []


def test_empty_when_nothing_related_or_malformed():
    rec = MemoryReconciler(ScriptedLLM(['[{"id":"a1","action":"delete"}]']))
    assert rec.review("u", "a", []) == []
    for bad in ["nope", "{}", "", "[1,2,3]"]:
        assert MemoryReconciler(ScriptedLLM([bad])).review("u", "a", [_mem("a1", "x")]) == []
