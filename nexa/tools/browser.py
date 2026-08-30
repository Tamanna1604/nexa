"""Optional: actually drive Chrome to click through to playback.

Off unless BROWSER_AUTOMATION=true AND Playwright is installed:

    pip install playwright
    playwright install chromium

How it works: Nexa makes sure a Chrome is running with a remote-debugging
port open on a dedicated profile dir (BROWSER_PROFILE_DIR), connects to it
over the DevTools protocol, navigates, and clicks Play. It connects and
*disconnects* - it never closes Chrome - so the video keeps playing.

The first time you use it, log into Netflix / Prime / Hotstar once in that
Chrome window; the session persists in the profile dir after that.

Streaming sites change their markup and run A/B tests, so the click-through
is best-effort. If a step misses, Nexa still leaves you on the right page.
"""

from __future__ import annotations

import re
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import quote_plus

from nexa.config import settings

_PORT = 9222
_CONNECT_TIMEOUT_S = 12
_STEP_TIMEOUT_MS = 9000


# ----------------------------------------------------------------------
# is this path even available?
# ----------------------------------------------------------------------
def available() -> bool:
    if not settings.BROWSER_AUTOMATION:
        return False
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return _find_chrome() is not None


def _find_chrome() -> str | None:
    for name in ("chrome", "google-chrome", "chrome.exe"):
        found = shutil.which(name)
        if found:
            return found
    for p in (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/bin/google-chrome",
    ):
        if Path(p).exists():
            return p
    return None


def _port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _ensure_chrome() -> bool:
    """Guarantee a debuggable Chrome on _PORT, launching one if needed."""
    if _port_open(_PORT):
        return True
    exe = _find_chrome()
    if not exe:
        return False
    profile = settings.BROWSER_PROFILE_DIR
    Path(profile).mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        [
            exe,
            f"--remote-debugging-port={_PORT}",
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "https://www.google.com",
        ],
        close_fds=True,
    )
    for _ in range(int(_CONNECT_TIMEOUT_S / 0.25)):
        if _port_open(_PORT):
            time.sleep(1.0)  # let the DevTools endpoint come fully up
            return True
        time.sleep(0.25)
    return False


# ----------------------------------------------------------------------
# per-service click-through
# ----------------------------------------------------------------------
def _pick_netflix_profile(page) -> None:
    """Clear the 'Who's watching?' gate, choosing NETFLIX_PROFILE if it shows."""
    want = (settings.NETFLIX_PROFILE or "").strip()
    sel = '[data-uia="profile-link"], .profile-link, a.profile-icon'
    try:
        page.wait_for_selector(sel, timeout=5000)
    except Exception:  # noqa: BLE001 - no gate, already inside a profile
        return
    try:
        if want:
            named = page.locator(sel).filter(has_text=want)
            if named.count():
                named.first.click(timeout=_STEP_TIMEOUT_MS)
                page.wait_for_timeout(2500)
                return
        page.locator(sel).first.click(timeout=_STEP_TIMEOUT_MS)
        page.wait_for_timeout(2500)
    except Exception:  # noqa: BLE001
        pass


def _netflix(page, title: str) -> str:
    page.goto("https://www.netflix.com/browse", wait_until="domcontentloaded")
    page.wait_for_timeout(2000)
    if "/login" in page.url:
        return "log into Netflix in the Nexa Chrome window first, then try again."
    _pick_netflix_profile(page)

    page.goto(
        f"https://www.netflix.com/search?q={quote_plus(title)}",
        wait_until="domcontentloaded",
    )
    page.wait_for_timeout(2500)
    if "/login" in page.url:
        return "log into Netflix in the Nexa Chrome window first, then try again."

    card = page.locator('a[href*="/watch/"], a[href*="/title/"]').first
    try:
        card.wait_for(timeout=_STEP_TIMEOUT_MS)
    except Exception:  # noqa: BLE001
        return f"opened Netflix search for '{title}' — pick the show yourself."

    href = card.get_attribute("href") or ""
    m = re.search(r"/(?:watch|title)/(\d+)", href)
    if m:
        page.goto(
            f"https://www.netflix.com/watch/{m.group(1)}",
            wait_until="domcontentloaded",
        )
        return f"Playing '{title}' on Netflix."

    try:
        card.click(timeout=_STEP_TIMEOUT_MS)
        page.wait_for_timeout(1500)
        page.get_by_role("button", name=re.compile("play", re.I)).first.click(
            timeout=_STEP_TIMEOUT_MS
        )
        return f"Playing '{title}' on Netflix."
    except Exception:  # noqa: BLE001
        return f"Opened '{title}' on Netflix — press play in the Chrome window."


def _generic(page, title: str, search_url: str, label: str) -> str:
    page.goto(search_url.format(q=quote_plus(title)), wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    for sel in (
        'a[href*="/detail"]',
        'a[href*="/movies/"]',
        'a[href*="/shows/"]',
        'a[href*="/title"]',
        '[data-testid*="card"] a',
        "article a",
    ):
        loc = page.locator(sel).first
        try:
            if loc.count() and loc.is_visible():
                loc.click(timeout=_STEP_TIMEOUT_MS)
                page.wait_for_timeout(2000)
                break
        except Exception:  # noqa: BLE001
            continue
    try:
        page.get_by_role("button", name=re.compile(r"play|watch now", re.I)).first.click(
            timeout=_STEP_TIMEOUT_MS
        )
        return f"Playing '{title}' on {label}."
    except Exception:  # noqa: BLE001
        return f"Opened '{title}' on {label} — press play in the Chrome window."


_SEARCH_URLS = {
    "prime": "https://www.primevideo.com/search/ref=atv_nb_sr?phrase={q}",
    "hotstar": "https://www.hotstar.com/in/search?q={q}",
    "youtube": "https://www.youtube.com/results?search_query={q}",
}


def _play_worker(service_key: str, title: str, out: dict[str, str]) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        out["msg"] = (
            "browser automation needs `pip install playwright` "
            "then `playwright install chromium`."
        )
        return
    if not _ensure_chrome():
        out["msg"] = "couldn't start a debuggable Chrome — is Chrome installed?"
        return
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(f"http://localhost:{_PORT}")
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.new_page()
            if service_key == "netflix":
                out["msg"] = _netflix(page, title)
            elif service_key == "youtube":
                out["msg"] = _generic(page, title, _SEARCH_URLS["youtube"], "YouTube")
            elif service_key == "prime":
                out["msg"] = _generic(page, title, _SEARCH_URLS["prime"], "Prime Video")
            elif service_key == "hotstar":
                out["msg"] = _generic(page, title, _SEARCH_URLS["hotstar"], "JioHotstar")
            else:
                out["msg"] = f"don't know how to drive {service_key}."
            browser.close()  # CDP: detaches only, Chrome + playback stay up
    except Exception as exc:  # noqa: BLE001
        out["msg"] = f"browser automation hit an error ({exc})."


def play(service_key: str, title: str) -> str:
    """Blocking, but capped: drive Chrome to play `title`. Returns a status line."""
    out: dict[str, str] = {}
    t = threading.Thread(
        target=_play_worker, args=(service_key, title, out), daemon=True
    )
    t.start()
    t.join(timeout=60)
    if t.is_alive():
        return (
            f"Started Chrome for '{title}' — it's still loading, "
            f"finish from the browser window."
        )
    return out.get("msg", "Couldn't drive the browser.")
