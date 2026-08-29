"""Reconcile stored memories against what the user just said.

For each related memory the model chooses one of:
  keep    - still true, or just extra detail -> do nothing
  update  - the situation changed but the useful info (a name!) should survive
            -> rephrase it. "boyfriend named Rohan" + "we broke up"
               becomes "Rohan is the user's ex-boyfriend".
  delete  - the memory is simply WRONG now: a correction ("his name is Ravi,
            not Karan"), a denial ("I don't have a brother"), or a moved fact
            ("I live in Delhi" replacing "lives in Pune").

`update` exists so a breakup / job change / move doesn't nuke the name or
detail attached to the old fact.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from nexa.models import Memory
from nexa.providers.base import LLMClient

_SYSTEM = """You maintain a user's long-term memory. You get the latest thing the user
said and a numbered list of stored memories that might be affected.

For each memory that needs a change, output an object:
  {"id": "<id>", "action": "update", "text": "<rephrased fact>"}   OR
  {"id": "<id>", "action": "delete"}

Use "update" when the situation changed but a name or detail is still worth
keeping:
  "User has a boyfriend named Rohan" + user says they broke up
      -> {"id": "..", "action": "update", "text": "Rohan is the user's ex-boyfriend."}
  "User works at Acme" + user says they changed jobs to Globex
      -> {"id": "..", "action": "update", "text": "User used to work at Acme."}

Use "delete" only when the memory is now simply WRONG:
  correction ("his name is Ravi, not Karan")  -> delete the "Karan" memory
  denial ("I don't have a brother")           -> delete the brother memory
  replaced fact ("I moved to Delhi")          -> delete "lives in Pune"

Do nothing for memories that are still true or are just extra detail.
Output ONLY a JSON array of change objects. If nothing changes, output []."""

_EXAMPLE_USER = (
    'LATEST USER MESSAGE: "yeah we broke up last week unfortunately"\n\n'
    "RELATED MEMORIES:\n"
    '  id=a1 | User has a boyfriend named Rohan.\n'
    '  id=a2 | User has been dating Rohan for two years.\n'
    '  id=a3 | User works at ZS Associates.'
)
_EXAMPLE_REPLY = (
    '[{"id": "a1", "action": "update", "text": "Rohan is the user\'s ex-boyfriend."}, '
    '{"id": "a2", "action": "update", "text": "User dated Rohan for about two years."}]'
)


@dataclass
class MemoryChange:
    id: str
    action: str          # "update" | "delete"
    text: str = ""       # new text, for "update"


class MemoryReconciler:
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def review(
        self,
        user_message: str,
        assistant_message: str,
        related: list[Memory],
    ) -> list[MemoryChange]:
        if not related:
            return []
        listing = "\n".join(f"  id={m.id} | {m.text}" for m in related)
        messages = [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": _EXAMPLE_USER},
            {"role": "assistant", "content": _EXAMPLE_REPLY},
            {
                "role": "user",
                "content": (
                    f'LATEST USER MESSAGE: "{user_message}"\n'
                    f'ASSISTANT REPLY: "{assistant_message}"\n\n'
                    f"RELATED MEMORIES:\n{listing}"
                ),
            },
        ]
        try:
            raw = self._llm.chat(messages)
        except Exception as exc:  # noqa: BLE001
            print(f"[nexa] memory reconciliation skipped ({exc})")
            return []
        from nexa.config import settings

        if settings.DEBUG_PROMPT:
            print(f"\n>>> RECONCILER input:\n{messages[-1]['content']}\n>>> RECONCILER raw output:\n{raw}\n")

        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not match:
            return []
        try:
            items = json.loads(match.group(0))
        except json.JSONDecodeError:
            return []
        if not isinstance(items, list):
            return []

        valid = {m.id for m in related}
        out: list[MemoryChange] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            mid = str(it.get("id", ""))
            action = str(it.get("action", "")).lower()
            if mid not in valid or action not in {"update", "delete"}:
                continue
            text = str(it.get("text", "")).strip()
            if action == "update" and not text:
                continue
            out.append(MemoryChange(id=mid, action=action, text=text))
        return out
