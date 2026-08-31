"""One-time: open Nexa's automation Chrome window so you can log in.

    python -m scripts.setup_browser

The `watch` tool that clicks through to playback drives its OWN Chrome
profile (BROWSER_PROFILE_DIR) - Chrome blocks automation on your normal
profile, and modern Chrome's App-Bound cookie encryption stops us seeding
it from your real profile. So this opens that window once; you sign into
Netflix / Prime Video / JioHotstar in it, and the sessions persist there.
It runs alongside your main Chrome - the two don't interfere.

Re-run any time to get back into that window (e.g. a session expired).
Add --reset to wipe the profile and start clean.
"""

from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

from nexa.config import settings
from nexa.tools import browser as b


def main(argv: list[str]) -> None:
    prof = Path(settings.BROWSER_PROFILE_DIR)

    if "--reset" in argv and prof.exists():
        shutil.rmtree(prof, ignore_errors=True)
        print(f"wiped {prof}")

    if b._port_open(b._PORT):
        print(f"Automation Chrome is already running (port {b._PORT}).")
    else:
        # force the isolated-profile path regardless of CHROME_USE_REAL_PROFILE
        real, settings.CHROME_USE_REAL_PROFILE = settings.CHROME_USE_REAL_PROFILE, False
        ok, note = b._ensure_chrome()
        settings.CHROME_USE_REAL_PROFILE = real
        if not ok:
            print(f"Couldn't start it: {note}")
            return
        time.sleep(1)
        print(f"Opened Nexa's automation Chrome (profile: {prof}).")

    print(
        "\nIn THAT window, sign into what you want Nexa to use:\n"
        "  - https://web.whatsapp.com      (scan the QR with your phone)\n"
        "  - https://www.netflix.com/login\n"
        "  - https://www.primevideo.com\n"
        "  - https://www.hotstar.com/in\n"
        "\nLeave it open (or close it - the logins are saved). Then:\n"
        '  py run.py   ->   "Nexa, play Friends on Netflix"  /  "any unread whatsapp?"\n'
    )


if __name__ == "__main__":
    main(sys.argv[1:])
