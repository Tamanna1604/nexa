"""Optional: actually drive Chrome to click through to playback.

Off by default. The normal `watch` path just opens the service's search page
in a new tab (nexa/tools/streaming.py) - simple and reliable.

This module is only used when BROWSER_AUTOMATION=true AND Playwright is
installed (`pip install playwright && playwright install chromium`). It needs
a Chrome with a remote-debugging port open, which has two catches:

  * Chrome allows one process per profile, so Nexa force-closes a running
    Chrome and relaunches it with the port (tabs restore via
    --restore-last-session).
  * MODERN CHROME REFUSES --remote-debugging-port ON THE DEFAULT PROFILE DIR.
    So CHROME_USE_REAL_PROFILE=true against the auto-detected dir will fail
    with "didn't open its debugging port". Point CHROME_USER_DATA_DIR at a
    custom (non-default) folder, or set CHROME_USE_REAL_PROFILE=false to use
    the isolated BROWSER_PROFILE_DIR (log into each service once).

Streaming sites change their markup and run A/B tests, so the click-through
is best-effort. If a step misses, Nexa still leaves you on the right page.
"""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import quote_plus

from nexa.config import settings

_PORT = 9222
_CONNECT_TIMEOUT_S = 20
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


def _cdp_ready() -> bool:
    """The DevTools HTTP endpoint is up AND serving a browser target."""
    import json
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{_PORT}/json/version", timeout=2) as r:
            return bool(json.loads(r.read()).get("webSocketDebuggerUrl"))
    except Exception:  # noqa: BLE001
        return False


def _default_user_data_dir() -> str | None:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        cand = Path(base) / "Google" / "Chrome" / "User Data" if base else None
    elif sys.platform == "darwin":
        cand = Path.home() / "Library" / "Application Support" / "Google" / "Chrome"
    else:
        cand = Path.home() / ".config" / "google-chrome"
    return str(cand) if cand and cand.exists() else None


def _chrome_running() -> bool:
    try:
        if sys.platform == "win32":
            out = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq chrome.exe", "/NH"],
                capture_output=True, text=True, timeout=10,
            )
            return "chrome.exe" in out.stdout.lower()
        return subprocess.run(
            ["pgrep", "-x", "chrome"], capture_output=True, timeout=10
        ).returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _close_chrome() -> bool:
    """Fully terminate Chrome so a fresh instance can own the debug port.

    Chrome refuses `--remote-debugging-port` while ANY chrome.exe is alive for
    that profile (it just hands the URL to the running instance - "Opening in
    existing browser session"). Background-apps mode keeps chrome.exe alive
    after the windows close, so this force-kills the whole tree. Chrome treats
    the next start as crash recovery; `--restore-last-session` brings tabs back.
    """
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/IM", "chrome.exe", "/T"],
                           capture_output=True, timeout=20)
        else:
            subprocess.run(["pkill", "-KILL", "-x", "chrome"],
                           capture_output=True, timeout=20)
    except Exception:  # noqa: BLE001
        pass
    for _ in range(16):
        if not _chrome_running():
            time.sleep(1.0)  # let Windows release the profile lock
            return True
        time.sleep(0.5)
    return not _chrome_running()


def _ensure_chrome() -> tuple[bool, str]:
    """Guarantee a debuggable Chrome on _PORT. Returns (ok, note-for-the-user)."""
    if _cdp_ready():
        return True, ""
    exe = _find_chrome()
    if not exe:
        return False, "I can't find Chrome on this machine."

    args = [
        f"--remote-debugging-port={_PORT}",
        "--no-first-run",
        "--no-default-browser-check",
        "--restore-last-session",
    ]
    note = ""

    if settings.CHROME_USE_REAL_PROFILE:
        udd = (settings.CHROME_USER_DATA_DIR or "").strip() or _default_user_data_dir()
        if not udd:
            return False, (
                "couldn't find your Chrome 'User Data' folder - set "
                "CHROME_USER_DATA_DIR in .env (see chrome://version)."
            )
        prof = (settings.CHROME_PROFILE_DIRECTORY or "Default").strip()
        args += [f"--user-data-dir={udd}", f"--profile-directory={prof}"]
        if _chrome_running():
            if not _close_chrome():
                return False, (
                    "I couldn't close your running Chrome, so I can't attach a "
                    "debugging port to it (Chrome allows one process per "
                    "profile). Quit Chrome fully and try again."
                )
            note = "restarted Chrome to attach to your logged-in session - "
    else:
        udd = settings.BROWSER_PROFILE_DIR
        Path(udd).mkdir(parents=True, exist_ok=True)
        args.append(f"--user-data-dir={udd}")

    subprocess.Popen([exe, *args, "about:blank"], close_fds=True)
    for _ in range(int(_CONNECT_TIMEOUT_S / 0.25)):
        if _cdp_ready():
            time.sleep(1.0)
            return True, note
        time.sleep(0.25)
    hint = (
        " (Chrome may have handed off to a still-running instance - check for "
        "background chrome.exe processes.)"
        if _chrome_running()
        else ""
    )
    return False, f"Chrome didn't open its debugging port in time.{hint}"


# ----------------------------------------------------------------------
# per-service click-through
# ----------------------------------------------------------------------
def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _pick_netflix_profile(page) -> str | None:
    """Clear the 'Who's watching?' gate. Returns None on success, or a message
    for the user if the wanted profile couldn't be matched."""
    want = (settings.NETFLIX_PROFILE or "").strip()
    sel = '[data-uia="profile-link"], .profile-link, a.profile-icon, .choose-profile a'
    try:
        page.wait_for_selector(sel, timeout=6000)
    except Exception:  # noqa: BLE001 - no gate, already inside a profile
        return None

    links = page.locator(sel)
    names: list[str] = []
    for i in range(min(links.count(), 8)):
        try:
            names.append(links.nth(i).inner_text().strip().splitlines()[0].strip())
        except Exception:  # noqa: BLE001
            names.append("")

    try:
        if want:
            wn = _norm(want)
            for i, nm in enumerate(names):
                nn = _norm(nm)
                if nn and (wn in nn or nn in wn or nn[:4] == wn[:4]):
                    links.nth(i).click(timeout=_STEP_TIMEOUT_MS)
                    page.wait_for_timeout(2500)
                    return None
            seen = ", ".join(n for n in names if n) or "none visible"
            return (
                f"I couldn't find a Netflix profile matching '{want}'. "
                f"Profiles on the account: {seen}. Set NETFLIX_PROFILE to one of these."
            )
        links.first.click(timeout=_STEP_TIMEOUT_MS)
        page.wait_for_timeout(2500)
    except Exception:  # noqa: BLE001
        pass
    return None


def _netflix(page, title: str) -> str:
    page.goto("https://www.netflix.com/browse", wait_until="domcontentloaded")
    page.wait_for_timeout(2000)
    if "/login" in page.url:
        return (
            "Netflix isn't signed in on this Chrome profile. Open Chrome, sign "
            "into Netflix, then try again (or set CHROME_PROFILE_DIRECTORY to "
            "the profile that has Netflix)."
        )
    gate_msg = _pick_netflix_profile(page)
    if gate_msg:
        return gate_msg

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


_PLAYERS = {
    "netflix": lambda page, title: _netflix(page, title),
    "youtube": lambda page, title: _generic(page, title, _SEARCH_URLS["youtube"], "YouTube"),
    "prime": lambda page, title: _generic(page, title, _SEARCH_URLS["prime"], "Prime Video"),
    "hotstar": lambda page, title: _generic(page, title, _SEARCH_URLS["hotstar"], "JioHotstar"),
}


def play(service_key: str, title: str) -> str:
    """Drive the automation Chrome to play `title`. Returns a status line."""
    drive = _PLAYERS.get(service_key)
    if not drive:
        return f"I don't know how to drive {service_key}."
    return with_page(lambda page: drive(page, title), timeout=110, close_new=False)


# ----------------------------------------------------------------------
# generic: run a function against a Playwright page in the automation Chrome
# ----------------------------------------------------------------------
def with_page(fn, *, url_hint: str = "", timeout: int = 90, close_new: bool = True) -> str:
    """Run fn(page) on a page connected to the automation Chrome over CDP.

    If url_hint is given and a tab already has it in its URL, that tab is reused
    and left open. Otherwise a fresh tab is opened; it is closed afterwards
    unless close_new=False (e.g. a video that must keep playing).
    fn must return a string. Runs in a worker thread with a hard time cap.
    """
    out: dict[str, str] = {}

    def worker() -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            out["msg"] = "this needs `pip install playwright` then `playwright install chromium`."
            return
        ok, note = _ensure_chrome()
        if not ok:
            out["msg"] = note or "couldn't start a debuggable Chrome."
            return
        try:
            with sync_playwright() as pw:
                browser = None
                for attempt in range(3):
                    try:
                        browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{_PORT}")
                        break
                    except Exception:  # noqa: BLE001 - transient WS reset; retry
                        time.sleep(1.5)
                if browser is None:
                    out["msg"] = "couldn't attach to the Nexa Chrome window - try once more."
                    return
                ctx = browser.contexts[0] if browser.contexts else browser.new_context()
                reused = None
                if url_hint:
                    for pg in ctx.pages:
                        if url_hint in (pg.url or ""):
                            reused = pg
                            break
                page = reused or ctx.new_page()
                try:
                    out["msg"] = fn(page)
                finally:
                    if reused is None and close_new:
                        try:
                            page.close()
                        except Exception:  # noqa: BLE001
                            pass
                browser.close()  # CDP: detaches only, Chrome stays up
        except Exception as exc:  # noqa: BLE001
            out["msg"] = f"browser automation error ({exc})."

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout=timeout)
    if t.is_alive():
        return "the browser is still working on that — check the Nexa Chrome window."
    return out.get("msg", "couldn't drive the browser.")
