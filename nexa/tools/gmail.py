"""Read the user's recent Gmail over IMAP (read-only, never marks mail read).

Setup: turn on 2-step verification, create an App Password at
myaccount.google.com/apppasswords, and put it in .env:

    GMAIL_ADDRESS=you@gmail.com
    GMAIL_APP_PASSWORD=abcd efgh ijkl mnop

Uses BODY.PEEK so opening a message here does NOT mark it read in Gmail.
"""

from __future__ import annotations

import email
import imaplib
import re
from email.header import decode_header, make_header
from email.utils import parseaddr
from typing import Any

from nexa.config import settings
from nexa.tools.base import Tool

_HOST = "imap.gmail.com"


def _decode(raw: str | None) -> str:
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(raw)))
    except Exception:  # noqa: BLE001
        return raw


def _body_snippet(msg: email.message.Message, limit: int = 240) -> str:
    text = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(
                part.get("Content-Disposition")
            ):
                try:
                    text = part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", "replace"
                    )
                    break
                except Exception:  # noqa: BLE001
                    continue
    else:
        try:
            text = msg.get_payload(decode=True).decode(
                msg.get_content_charset() or "utf-8", "replace"
            )
        except Exception:  # noqa: BLE001
            text = ""
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


class GmailTool(Tool):
    name = "gmail"
    description = (
        "Read the user's recent Gmail. action='unread' lists unread inbox "
        "messages; action='latest' the most recent messages; action='from' with "
        "'sender' the latest from that person or company. Returns who it's from, "
        "the subject, and a short snippet. Read-only - it never marks mail read."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["unread", "latest", "from"]},
            "sender": {"type": "string", "description": "Name or address for action='from'."},
            "count": {"type": "integer", "description": "How many to fetch (default 5, max 15)."},
        },
        "required": ["action"],
    }

    def run(
        self,
        action: str = "unread",
        sender: str | None = None,
        count: int = 5,
        **kwargs: Any,
    ) -> str:
        addr = (settings.GMAIL_ADDRESS or "").strip()
        pw = (settings.GMAIL_APP_PASSWORD or "").replace(" ", "")
        if not addr or not pw:
            return (
                "Gmail isn't set up. Add GMAIL_ADDRESS and GMAIL_APP_PASSWORD (a "
                "Google App Password) to .env."
            )
        count = max(1, min(15, int(count or 5)))

        try:
            M = imaplib.IMAP4_SSL(_HOST)
            M.login(addr, pw)
            M.select("INBOX", readonly=True)
            if action == "from" and sender:
                typ, data = M.search(None, "FROM", f'"{sender}"')
                label = f"Latest email from {sender}"
            elif action == "unread":
                typ, data = M.search(None, "UNSEEN")
                label = "Your unread emails"
            else:
                typ, data = M.search(None, "ALL")
                label = "Your latest emails"

            ids = (data[0].split() if data and data[0] else [])[-count:][::-1]
            if not ids:
                M.logout()
                return "Nothing found." if action == "from" else "No unread emails."

            items = []
            for num in ids:
                typ, raw = M.fetch(num, "(BODY.PEEK[])")
                if not raw or not raw[0]:
                    continue
                msg = email.message_from_bytes(raw[0][1])
                frm_name, frm_addr = parseaddr(_decode(msg.get("From")))
                who = frm_name or frm_addr or "unknown"
                subj = _decode(msg.get("Subject")) or "(no subject)"
                snip = _body_snippet(msg)
                items.append(f'- From {who} — "{subj}": {snip}')
            M.logout()
        except imaplib.IMAP4.error as exc:
            return (
                f"Gmail login failed ({exc}). Check GMAIL_APP_PASSWORD is an App "
                f"Password (not your normal password) and 2-step is on."
            )
        except Exception as exc:  # noqa: BLE001
            return f"Couldn't reach Gmail ({exc})."

        if not items:
            return "Couldn't read those emails."
        return f"{label}\n" + "\n".join(items) + "\n~ Gmail inbox"
