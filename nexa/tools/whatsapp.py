"""Open a WhatsApp chat with a contact, optionally send a line, optionally call.

Reliable:  opening the chat  (whatsapp://send?phone=...)
Reliable:  pre-filling a message to send
Best-effort: actually sending (pressing Enter) and placing a call - WhatsApp
exposes no API, so we drive the desktop UI. Needs ALLOW_UI_AUTOMATION=true.
Sending uses pywinauto if installed, otherwise a keystroke via PowerShell on
Windows (no extra package). A call needs pywinauto. UI automation can break on
a WhatsApp update.
"""

from __future__ import annotations

import subprocess
import sys
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
        "send); action='send' opens it AND presses Enter to actually send the "
        "message; action='call' opens the chat and tries to start a voice call. "
        "'send' and 'call' need UI automation enabled. Match the contact by "
        "first name."
    )
    parameters = {
        "type": "object",
        "properties": {
            "contact": {"type": "string", "description": "Contact name, e.g. 'Vrinda'."},
            "action": {"type": "string", "enum": ["open", "message", "send", "call"]},
            "message": {
                "type": "string",
                "description": "Text for action='message' or action='send'.",
            },
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
        if action in ("message", "send") and message:
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
        if action == "send":
            if not message:
                return f"Opened {c.name}'s chat — what should I send?"
            ok, note = self._try_send()
            if ok:
                return f'Sent to {c.name} on WhatsApp: "{message}"'
            return f"Opened {c.name}'s chat with your message typed — {note}"
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

    # ------------------------------------------------------------------
    def _try_send(self) -> tuple[bool, str]:
        """Press Enter in the WhatsApp window to send the pre-typed text.

        Tries pywinauto first (focuses the WhatsApp window explicitly); falls
        back to a PowerShell keystroke on Windows so no extra package is needed.
        """
        if not settings.ALLOW_UI_AUTOMATION:
            return False, "set ALLOW_UI_AUTOMATION=true in .env for me to send it."

        # 1) pywinauto - precise, focuses the right window
        try:
            from pywinauto import Desktop
            from pywinauto.keyboard import send_keys

            time.sleep(2.5)  # let the chat load and the text pre-fill
            win = Desktop(backend="uia").window(title_re=".*WhatsApp.*")
            win.set_focus()
            time.sleep(0.3)
            send_keys("{ENTER}")
            return True, ""
        except ImportError:
            pass  # not installed - try the no-dependency path
        except Exception as exc:  # noqa: BLE001
            return False, f"couldn't drive the WhatsApp window ({exc})."

        # 2) no package: WhatsApp is foreground after the URI opens it; send Enter
        if sys.platform == "win32":
            try:
                subprocess.run(
                    [
                        "powershell", "-NoProfile", "-Command",
                        "Start-Sleep -Seconds 3; "
                        "(New-Object -ComObject WScript.Shell).SendKeys('~')",
                    ],
                    check=True,
                    timeout=15,
                    creationflags=0x08000000,  # CREATE_NO_WINDOW
                )
                return True, ""
            except Exception as exc:  # noqa: BLE001
                return False, f"couldn't send the keystroke ({exc})."
        return False, "press Enter to send (`pip install pywinauto` for auto-send)."
