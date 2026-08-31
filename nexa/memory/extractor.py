"""Decide what (if anything) from a finished turn is worth remembering forever.

This is a small LLM call with a strict JSON contract. Not every message should
become permanent memory - the prompt is written to return `[]` for smalltalk.
"""

from __future__ import annotations

import json
import re

from nexa.providers.base import LLMClient

# facts that shouldn't have been extracted - drop them post-parse
_JUNK = re.compile(
    r"\b(is asking|asked about|wants to know|is wondering|is curious)\b"
    r"|current (date|time)|it is \w+day, \d",
    re.IGNORECASE,
)

_SYSTEM = """You read the latest exchange (with a little prior context) and pull out
facts about the USER that are worth remembering for future conversations.

Return ONLY a JSON array. Each item:
  {"text": "<self-contained fact, third person, starts with 'User' or a name>", "type": "<category>", "importance": <1-10>}

Categories: preference, goal, instruction, relationship, fact, trait, habit, activity.

DO capture, even from partial or offhand mentions:
- People in the user's life + any detail (name, where they live, what they do)
  -> type "relationship", importance 7-9. "my brother in Bangalore" is enough to
  record "User has a brother who lives in Bangalore."
- Something the user DID -> type "activity", importance 3-5. Build a picture of
  their routine over time. CRITICAL: convert every relative time word to an
  absolute date using the "current time is ..." reference given below.
  "went to the gym this morning" on Sat 29 Aug -> "User went to the gym on the
  morning of Saturday 29 August 2026". "called mom yesterday" -> use the day
  before. Never store "this morning" / "today" / "yesterday" / "just now" as-is.
- What the user is currently reading / watching / building / studying / working on
  -> type "fact", importance 4-6
- Concrete things surfaced from the user's WhatsApp messages or emails that the
  assistant just read out: who contacted them and why, an invitation or plan, a
  commitment, a bill or payment due, an appointment, a deadline -> type "fact"
  or "activity", importance 5-7. Record the specifics ("Dhruv asked User to
  meet on Saturday at 5pm"), never "User has unread messages".
- Preferences, goals, standing instructions, routines, likes and dislikes
- Personal facts: where they live, their job, their studies, their name, festivals
  or events they take part in

Resolve pronouns using the prior context ("he" -> the brother just mentioned).
Every fact must stand on its own with no pronouns.

DO NOT capture:
- One-off feelings or state that changes hour to hour ("user is tired right now",
  "user dislikes arms today" - "today" makes it transient)
- The current date/time itself
- Facts about the assistant, or general world knowledge
- A question the user asked. Never output "User is asking...", "User wants to
  know...", "User asked about..." - a question is not a fact.

If nothing qualifies, return exactly: []
Prefer 1-3 short, specific items. Split compound statements into separate facts.
The example below only shows the FORMAT - never copy its content into your output;
extract only from the actual LATEST exchange you are given."""

_EXAMPLE_USER = (
    "PRIOR CONTEXT:\n"
    'user: my cousin priya just started a new job\n'
    'assistant: oh nice, doing what?\n\n'
    "LATEST:\n"
    'user: "she\'s a vet in chennai now. also i took up rock climbing last month"\n'
    'assistant: "that\'s great"'
)
_EXAMPLE_REPLY = (
    '[{"text": "User has a cousin named Priya.", "type": "relationship", "importance": 8}, '
    '{"text": "Priya works as a vet in Chennai.", "type": "fact", "importance": 6}, '
    '{"text": "User recently took up rock climbing.", "type": "habit", "importance": 5}]'
)


class MemoryExtractor:
    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    def extract(
        self,
        user_message: str,
        assistant_message: str,
        prior_context: list[dict] | None = None,
        now: str | None = None,
        known: list | None = None,
    ) -> list[dict]:
        ctx = ""
        if prior_context:
            lines = "\n".join(f'{m["role"]}: {m["content"]}' for m in prior_context[-4:])
            ctx = f"PRIOR CONTEXT:\n{lines}\n\n"
        known_block = ""
        if known:
            kl = "\n".join(f"- {getattr(m, 'text', m)}" for m in known[:8])
            known_block = (
                "ALREADY KNOWN about the user (do NOT re-state these; if a name in "
                "the latest message is a near-match to a name here, it is the SAME "
                "person - use the known spelling):\n" + kl + "\n\n"
            )
        # the clock is metadata for resolving "this morning" - NOT a fact to store
        stamp = f"[reference: the current time is {now} - do not store this]\n" if now else ""
        messages = [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": _EXAMPLE_USER},
            {"role": "assistant", "content": _EXAMPLE_REPLY},
            {
                "role": "user",
                "content": (
                    f'{ctx}{known_block}{stamp}LATEST EXCHANGE:\n'
                    f'user: "{user_message}"\nassistant: "{assistant_message}"'
                ),
            },
        ]
        try:
            raw = self._llm.chat(messages)
        except Exception as exc:  # noqa: BLE001 - never break a conversation
            print(f"[nexa] memory extraction skipped ({exc})")
            return []
        from nexa.config import settings

        if settings.DEBUG_PROMPT:
            print(f"\n>>> EXTRACTOR input:\n{messages[-1]['content']}\n>>> EXTRACTOR raw output:\n{raw}\n")
        return self._parse(raw)

    @staticmethod
    def _parse(raw: str) -> list[dict]:
        # Models sometimes wrap JSON in prose or ```json fences - grab the array.
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not match:
            return []
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return []
        if not isinstance(data, list):
            return []

        clean: list[dict] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text", "")).strip()
            if not text or _JUNK.search(text):
                continue
            try:
                importance = int(item.get("importance", 5))
            except (TypeError, ValueError):
                importance = 5
            clean.append(
                {
                    "text": text,
                    "type": str(item.get("type", "fact")).strip() or "fact",
                    "importance": max(1, min(10, importance)),
                }
            )
        return clean
