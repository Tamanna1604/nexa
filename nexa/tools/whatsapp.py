"""Open a WhatsApp chat with a contact, optionally send a line, optionally call.

Reliable:  opening the chat  (whatsapp://send?phone=...)
Reliable:  pre-filling a message to send
Best-effort: placing the call - WhatsApp exposes no API for this, so we drive
the desktop UI with pywinauto. Needs ALLOW_UI_AUTOMATION=true and
`pip install pywinauto`; it can break on a WhatsApp update.
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import quote

from nexa.config import settings
from nexa.tools.apps import _start
from nexa.tools.base import Tool
from nexa.tools.contacts import Contacts


class WhatsAppTool(Tool):
    name = "whatsapp"
    description = (
        "Open WhatsApp for a contact. action='open' just opens the chat; "
        "action='message' opens it with text pre-typed (the user still presses "
        "send); action='call' opens the chat and tries to start a voice call. "
        "Match the contact by first name."
    )
    parameters = {
        "type": "object",
        "properties": {
            "contact": {"type": "string", "description": "Contact name, e.g. 'Vrinda'."},
            "action": {"type": "string", "enum": ["open", "message", "call"]},
            "message": {"type": "string", "description": "Text for action='message'."},
        },
        "required": ["contact"],
    }

    def __init__(self, contacts: Contacts | None = None) -> None:
        self._contacts = contacts or Contacts()

    def run(
        self,
        contact: str | None = None,
        action: str = "open",
        message: str | None = None,
        **kwargs: Any,
    ) -> str:
        if not contact:
            return "Which contact?"
        self._contacts.reload()
        c = self._contacts.resolve(contact)
        if c is None:
            have = ", ".join(x.name for x in self._contacts.all()) or "none"
            return (
                f"I don't have a number for '{contact}'. Add it to "
                f"{settings.CONTACTS_FILE}. Contacts I have: {have}."
            )

        uri = f"whatsapp://send?phone={c.phone}"
        if action == "message" and message:
            uri += f"&text={quote(message)}"
        try:
            _start(uri)
        except Exception as exc:  # noqa: BLE001
            return f"Couldn't open WhatsApp ({exc})."

        if action == "call":
            ok, note = self._try_call()
            if ok:
                return f"Calling {c.name} on WhatsApp."
            return f"Opened {c.name}'s chat — {note}"
        if action == "message":
            return f"Opened {c.name}'s chat with your message ready to send."
        return f"Opened {c.name}'s chat on WhatsApp."

    # ------------------------------------------------------------------
    def _try_call(self) -> tuple[bool, str]:
        if not settings.ALLOW_UI_AUTOMATION:
            return False, "press the call button (UI automation is off)."
        try:
            from pywinauto import Desktop
        except ImportError:
            return False, "press the call button (`pip install pywinauto` to automate it)."

        time.sleep(2.5)  # let the chat load
        try:
            win = Desktop(backend="uia").window(title_re=".*WhatsApp.*")
            win.set_focus()
            for label in ("Audio call", "Voice call", "Call", "Start voice call"):
                try:
                    btn = win.child_window(title=label, control_type="Button")
                    if btn.exists(timeout=1):
                        btn.click_input()
                        return True, ""
                except Exception:  # noqa: BLE001 - try the next label
                    continue
        except Exception as exc:  # noqa: BLE001
            return False, f"couldn't drive the WhatsApp window ({exc})."
        return False, "couldn't find the call button — press it yourself."
