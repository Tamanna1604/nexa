"""A small name -> phone-number book Nexa can look people up in.

WhatsApp's own contacts are encrypted and unreadable, so you keep a plain
`contacts.json` (path in CONTACTS_FILE). Either shape works:

    {"vrinda": "+919876500000", "mom": "+919876511111"}

    [{"name": "Vrinda Cuchie Coo", "phone": "+91 98765 00000"},
     {"name": "Mom",               "phone": "+919876511111"}]

Lookups match on the FIRST word, case-insensitively - "call vrinda cuchie coo"
resolves to "Vrinda".
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from nexa.config import settings


@dataclass
class Contact:
    name: str
    phone: str          # digits only, with country code, no '+' or spaces

    @property
    def wa_number(self) -> str:
        return self.phone


def _clean_number(raw: str) -> str:
    return re.sub(r"\D", "", str(raw))


def _first_word(s: str) -> str:
    m = re.search(r"[a-z0-9]+", s.lower())
    return m.group(0) if m else ""


class Contacts:
    def __init__(self, path: str | None = None) -> None:
        self._path = Path(path or settings.CONTACTS_FILE)
        self._by_first: dict[str, Contact] = {}
        self.reload()

    def reload(self) -> None:
        self._by_first.clear()
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        items = (
            [{"name": k, "phone": v} for k, v in data.items()]
            if isinstance(data, dict)
            else data if isinstance(data, list)
            else []
        )
        for it in items:
            name = str(it.get("name", "")).strip()
            phone = _clean_number(it.get("phone", ""))
            if not name or not phone:
                continue
            key = _first_word(name)
            # first entry wins for a given first name
            self._by_first.setdefault(key, Contact(name=name, phone=phone))

    def resolve(self, query: str) -> Contact | None:
        """Match `query`'s first word against contacts' first names."""
        if not query:
            return None
        return self._by_first.get(_first_word(query))

    def all(self) -> list[Contact]:
        return list(self._by_first.values())
