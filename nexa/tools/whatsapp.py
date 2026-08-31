"""WhatsApp: open a chat, send a message, place a call, or read messages.

WhatsApp has no API. Two backends:
  * WhatsApp Web via Playwright (nexa/tools/whatsapp_web.py) - used for send /
    unread / read / latest when BROWSER_AUTOMATION is on. Reliable (real DOM).
    One-time QR scan in the Nexa Chrome window.
  * the desktop app via the whatsapp:// URI - used for open / message / call,
    and as the send fallback when browser automation is off. "send" and "call"
    then drive the app window (needs ALLOW_UI_AUTOMATION=true), which is fragile.
"""

from __future__ import annotations

import subprocess
import sys
import time
from typing import Any
from urllib.parse import quote

from nexa.config import settings
import nexa.tools.whatsapp_web as whatsapp_web
from nexa.tools.apps import _start
from nexa.tools.base import Tool
from nexa.tools.contacts import Contacts


class WhatsAppTool(Tool):
    name = "whatsapp"
    description = (
        "Act on WhatsApp for a contact. actions: 'open' opens the chat; "
        "'message' opens it with text pre-typed (user presses send); 'send' "
        "types AND sends the message; 'call' starts a voice call; 'unread' "
        "lists chats with unread messages (no contact needed); 'read' reads the "
        "recent messages in a contact's chat; 'latest' gives that contact's "
        "most recent message. Match the contact by first name."
    )
    parameters = {
        "type": "object",
        "properties": {
            "contact": {"type": "string", "description": "Contact name, e.g. 'Dhruv'."},
            "action": {
                "type": "string",
                "enum": ["open", "message", "send", "call", "unread", "read", "latest"],
            },
            "message": {
                "type": "string",
                "description": "Text for action='message' or action='send'.",
            },
        },
        "required": ["action"],
    }

    def __init__(self, contacts: Contacts | None = None) -> None:
        self._contacts = contacts or Contacts()

    # ------------------------------------------------------------------
    def run(
        self,
        contact: str | None = None,
        action: str = "open",
        message: str | None = None,
        **kwargs: Any,
    ) -> str:
        # read actions that don't need a contact
        if action == "unread":
            if not whatsapp_web.available():
                return _need_web()
            return whatsapp_web.unread()

        if not contact:
            return "Which contact?"
        self._contacts.reload()
        c = self._contacts.resolve(contact)
        name = c.name if c else contact

        # ---- WhatsApp Web actions (reliable) ----
        if action in ("read", "latest"):
            if not whatsapp_web.available():
                return _need_web()
            return (whatsapp_web.read if action == "read" else whatsapp_web.latest)(name)

        if action == "send" and message and whatsapp_web.available():
            return whatsapp_web.send(name, message)

        # ---- desktop-app actions (need a saved number) ----
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
            return f"Calling {c.name} on WhatsApp." if ok else f"Opened {c.name}'s chat — {note}"
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
        """Send the pre-typed text in the desktop app: click Send, else Enter.

        Fallback path only (WhatsApp Web is used when browser automation is on).
        The app is a WebView shell, so we wait for it, focus it, prefer the
        'Send' button, then a keystroke, with a couple of retries.
        """
        if not settings.ALLOW_UI_AUTOMATION:
            return False, "set ALLOW_UI_AUTOMATION=true (or BROWSER_AUTOMATION=true) so I can send it."

        delay = max(2.0, float(settings.WHATSAPP_SEND_DELAY))
        try:
            from pywinauto import Desktop
            from pywinauto.keyboard import send_keys

            win = None
            for _ in range(int(delay / 0.5) + 6):   # wait for the window + chat load
                try:
                    w = Desktop(backend="uia").window(title_re=".*WhatsApp.*")
                    if w.exists(timeout=0.5):
                        win = w
                        break
                except Exception:  # noqa: BLE001
                    pass
                time.sleep(0.5)
            if win is None:
                return False, "the WhatsApp window didn't come up."

            time.sleep(1.2)  # let the pre-filled text settle
            try:
                win.set_focus()
            except Exception:  # noqa: BLE001
                pass

            for attempt in range(3):
                # 1) the Send button, if UIA exposes it
                for label in ("Send", "Send message"):
                    try:
                        btn = win.child_window(title=label, control_type="Button")
                        if btn.exists(timeout=0.6):
                            btn.click_input()
                            return True, ""
                    except Exception:  # noqa: BLE001
                        pass
                # 2) keystroke into the focused (message) box
                try:
                    win.set_focus()
                    win.type_keys("{ENTER}", set_foreground=True)
                    return True, ""
                except Exception:  # noqa: BLE001
                    send_keys("{ENTER}")
                    return True, ""
                time.sleep(0.8)
        except ImportError:
            pass  # fall through to the no-package path
        except Exception as exc:  # noqa: BLE001
            return False, f"couldn't drive the WhatsApp window ({exc})."

        # no package: WhatsApp is foreground after the URI opens it; press Enter
        if sys.platform == "win32":
            try:
                subprocess.run(
                    [
                        "powershell", "-NoProfile", "-Command",
                        f"Start-Sleep -Seconds {int(max(3, delay))}; "
                        "$w = New-Object -ComObject WScript.Shell; "
                        "$w.AppActivate('WhatsApp') | Out-Null; Start-Sleep -Milliseconds 500; "
                        "$w.SendKeys('~')",
                    ],
                    check=True,
                    timeout=25,
                    creationflags=0x08000000,  # CREATE_NO_WINDOW
                )
                return True, ""
            except Exception as exc:  # noqa: BLE001
                return False, f"couldn't send the keystroke ({exc})."
        return False, "press Enter to send (`pip install pywinauto` for auto-send)."


def _need_web() -> str:
    return (
        "Reading and reliably sending WhatsApp needs the browser link. Set "
        "BROWSER_AUTOMATION=true, then run 'py -m scripts.setup_browser' and "
        "scan the WhatsApp Web QR once."
    )
