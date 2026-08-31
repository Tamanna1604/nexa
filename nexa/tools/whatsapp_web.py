"""Drive WhatsApp Web in the automation Chrome - reliable send + read.

WhatsApp has no API, but web.whatsapp.com has a real DOM, so this is far
steadier than poking the desktop app's window. One-time setup: open the Nexa
Chrome window (py -m scripts.setup_browser) and scan the WhatsApp Web QR once;
the linked session persists in the .nexa_browser profile.

Selectors track WhatsApp Web's current markup and can drift on an update -
every step is best-effort and degrades to a readable message.
"""

from __future__ import annotations

import re

import nexa.tools.browser as browser

_WA = "https://web.whatsapp.com/"
_SEARCH = (
    'div[contenteditable="true"][data-tab="3"], '
    '[aria-label="Search input textbox"], [aria-label="Search text"]'
)
_MSGBOX = (
    'div[contenteditable="true"][data-tab="10"], '
    'div[contenteditable="true"][aria-label="Type a message"]'
)
_ROWS = '#pane-side [role="listitem"], #pane-side [role="row"]'
_MSGS = "div.message-in, div.message-out"


def available() -> bool:
    return browser.available()


# ---------------------------------------------------------------- helpers
def _open(page) -> str | None:
    """Ensure web.whatsapp.com is loaded and linked. Returns an error msg or None."""
    if _WA not in (page.url or ""):
        page.goto(_WA, wait_until="domcontentloaded")
    for _ in range(30):  # up to ~30s for the app to come up
        if page.locator("#pane-side").count():
            page.wait_for_timeout(600)
            return None
        if page.locator('canvas[aria-label*="Scan"], [data-testid="qrcode"]').count():
            return (
                "WhatsApp Web isn't linked. Open the Nexa Chrome window and scan "
                "the QR at web.whatsapp.com with your phone, then try again."
            )
        page.wait_for_timeout(1000)
    return "WhatsApp Web didn't finish loading — try again in a moment."


def _open_chat(page, name: str) -> bool:
    box = page.locator(_SEARCH).first
    try:
        box.click(timeout=6000)
        box.fill("") if box.get_attribute("contenteditable") is None else box.press("Control+A")
        page.keyboard.type(name, delay=25)
    except Exception:  # noqa: BLE001
        return False
    page.wait_for_timeout(1600)
    row = page.locator(_ROWS).first
    try:
        row.click(timeout=6000)
    except Exception:  # noqa: BLE001
        return False
    page.wait_for_timeout(1600)
    return True


def _row_text(row) -> str:
    try:
        return re.sub(r"\s+", " ", row.inner_text()).strip()
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------- actions
def unread(limit: int = 8) -> str:
    def fn(page):
        err = _open(page)
        if err:
            return err
        rows = page.locator(_ROWS)
        found = []
        for i in range(min(rows.count(), 40)):
            r = rows.nth(i)
            if not r.locator('span[aria-label*="unread"]').count():
                continue
            t = _row_text(r)
            if t:
                found.append(t)
            if len(found) >= limit:
                break
        if not found:
            return "No unread WhatsApp chats right now."
        lines = "\n".join(f"- {t}" for t in found)
        return f"Unread WhatsApp chats\n{lines}\n~ WhatsApp Web"

    return browser.with_page(fn, url_hint="web.whatsapp.com", timeout=90, close_new=False)


def read(contact: str, count: int = 8) -> str:
    def fn(page):
        err = _open(page)
        if err:
            return err
        if not _open_chat(page, contact):
            return f"Couldn't open a chat with '{contact}'."
        msgs = page.locator(_MSGS)
        n = msgs.count()
        if not n:
            return f"No messages loaded for {contact}."
        out = []
        for i in range(max(0, n - count), n):
            m = msgs.nth(i)
            cls = m.get_attribute("class") or ""
            who = "You" if "message-out" in cls else contact
            txt = re.sub(r"\s+", " ", m.inner_text()).strip()
            txt = re.sub(r"\b\d{1,2}:\d{2}\s?[AaPp][Mm]\b$", "", txt).strip()
            if txt:
                out.append(f"- {who}: {txt}")
        return f"Last messages with {contact}\n" + "\n".join(out) + "\n~ WhatsApp Web"

    return browser.with_page(fn, url_hint="web.whatsapp.com", timeout=90, close_new=False)


def latest(contact: str) -> str:
    def fn(page):
        err = _open(page)
        if err:
            return err
        if not _open_chat(page, contact):
            return f"Couldn't open a chat with '{contact}'."
        incoming = page.locator("div.message-in")
        n = incoming.count()
        if not n:
            return f"No received messages from {contact} in view."
        txt = re.sub(r"\s+", " ", incoming.nth(n - 1).inner_text()).strip()
        txt = re.sub(r"\b\d{1,2}:\d{2}\s?[AaPp][Mm]\b$", "", txt).strip()
        return f'Latest from {contact}: "{txt}"'

    return browser.with_page(fn, url_hint="web.whatsapp.com", timeout=90, close_new=False)


def send(contact: str, message: str) -> str:
    def fn(page):
        err = _open(page)
        if err:
            return err
        if not _open_chat(page, contact):
            return f"Couldn't open a chat with '{contact}' to send the message."
        box = page.locator(_MSGBOX).first
        try:
            box.click(timeout=6000)
            page.keyboard.type(message, delay=12)
            page.wait_for_timeout(300)
        except Exception as exc:  # noqa: BLE001
            return f"Couldn't type the message ({exc})."
        btn = page.locator('button[aria-label="Send"], [data-icon="send"]').first
        try:
            if btn.count():
                btn.click(timeout=4000)
            else:
                page.keyboard.press("Enter")
        except Exception:  # noqa: BLE001
            page.keyboard.press("Enter")
        page.wait_for_timeout(600)
        return f'Sent to {contact} on WhatsApp: "{message}"'

    return browser.with_page(fn, url_hint="web.whatsapp.com", timeout=90, close_new=False)
