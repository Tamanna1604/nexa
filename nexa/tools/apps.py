"""Open an application on the user's computer, by name.

Deliberately narrow: it resolves a name to a known launch target (a URI
scheme, an .exe, or lets the OS resolve it) and starts it. It does NOT run
arbitrary commands, pass arguments, or take file paths from the model.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import Any

from nexa.config import settings
from nexa.tools.base import Tool

# name (lowercased) -> what to hand the OS. URI schemes work for Store apps.
_DEFAULT_ALIASES: dict[str, str] = {
    "whatsapp": "whatsapp:",
    "spotify": "spotify:",
    "telegram": "tg:",
    "slack": "slack:",
    "discord": "discord:",
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "settings": "ms-settings:",
    "chrome": "chrome",
    "edge": "msedge",
    "firefox": "firefox",
    "explorer": "explorer.exe",
    "files": "explorer.exe",
    "terminal": "wt.exe",
    "cmd": "cmd.exe",
    "vscode": "code",
    "vs code": "code",
    "code": "code",
}


def _aliases() -> dict[str, str]:
    merged = dict(_DEFAULT_ALIASES)
    for k, v in (settings.EXTRA_APP_ALIASES or {}).items():
        merged[k.strip().lower()] = str(v)
    return merged


def _start(target: str) -> None:
    """Launch a target: an .exe on PATH, a full path, a URI scheme, or a Store app."""
    if sys.platform == "win32":
        # bare exe name on PATH -> Popen it; everything else (URIs, paths,
        # protocols, Store-app monikers) -> let the shell resolve via `start`
        exe = shutil.which(target)
        if exe:
            subprocess.Popen([exe], close_fds=True)
        elif hasattr(os, "startfile") and (":" in target or os.path.exists(target)):
            os.startfile(target)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["cmd", "/c", "start", "", "/b", target], close_fds=True)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-a", target] if not target.endswith(":") else ["open", target])
    else:
        subprocess.Popen(["xdg-open", target])


class OpenAppTool(Tool):
    name = "open_app"
    description = (
        "Open or launch an application on the user's computer by name, e.g. "
        "'whatsapp', 'spotify', 'chrome', 'settings'. Only use it when the user "
        "clearly asks to open/launch/start an app."
    )
    parameters = {
        "type": "object",
        "properties": {
            "app": {
                "type": "string",
                "description": "The application name, e.g. 'whatsapp'.",
            }
        },
        "required": ["app"],
    }

    def run(self, app: str | None = None, **kwargs: Any) -> str:
        name = (app or "").strip().lower()
        if not name:
            return "Which app should I open?"

        target = _aliases().get(name, name)
        try:
            _start(target)
        except FileNotFoundError:
            return f"I couldn't find an app called '{app}' on this computer."
        except Exception as exc:  # noqa: BLE001
            return f"Couldn't open '{app}' ({exc})."
        return f"Opening {app}."
