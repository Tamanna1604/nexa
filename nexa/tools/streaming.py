"""Open a streaming service in the browser and jump to a title.

Netflix / Prime Video / JioHotstar / YouTube, all through the browser (no
desktop apps). Default behaviour: open the service's search page for the
title - the show is the first tile, one click plays it.

If BROWSER_AUTOMATION=true and Playwright is installed, action='play' goes
further: Nexa drives Chrome to click through to playback itself. See
nexa/tools/browser.py.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote_plus

import nexa.tools.browser as browser
from nexa.tools.apps import _start
from nexa.tools.base import Tool

# key -> (display name, search-URL template, home URL)
_SERVICES: dict[str, tuple[str, str, str]] = {
    "netflix": (
        "Netflix",
        "https://www.netflix.com/search?q={q}",
        "https://www.netflix.com",
    ),
    "prime": (
        "Prime Video",
        "https://www.primevideo.com/search/ref=atv_nb_sr?phrase={q}",
        "https://www.primevideo.com",
    ),
    "hotstar": (
        "JioHotstar",
        "https://www.hotstar.com/in/search?q={q}",
        "https://www.hotstar.com/in",
    ),
    "youtube": (
        "YouTube",
        "https://www.youtube.com/results?search_query={q}",
        "https://www.youtube.com",
    ),
}

# what the model / user might call each one
_ALIASES: dict[str, str] = {
    "netflix": "netflix",
    "prime": "prime",
    "prime video": "prime",
    "primevideo": "prime",
    "amazon": "prime",
    "amazon prime": "prime",
    "amazon prime video": "prime",
    "hotstar": "hotstar",
    "jiohotstar": "hotstar",
    "jio hotstar": "hotstar",
    "jio": "hotstar",
    "disney": "hotstar",
    "disney+": "hotstar",
    "disney plus": "hotstar",
    "disney hotstar": "hotstar",
    "youtube": "youtube",
    "yt": "youtube",
}


class StreamingTool(Tool):
    name = "watch"
    description = (
        "Watch something on a streaming service, all through the browser. "
        "'service' is netflix, prime (Amazon Prime Video), hotstar (JioHotstar) "
        "or youtube. Give 'title' for a specific show/movie; omit it to just "
        "open the service. action='play' tries to start playback directly; "
        "action='search' (default) just opens the search page. "
        "'play Friends on Netflix' -> watch(service='netflix', title='Friends', "
        "action='play')."
    )
    parameters = {
        "type": "object",
        "properties": {
            "service": {
                "type": "string",
                "description": "netflix | prime | hotstar | youtube",
            },
            "title": {
                "type": "string",
                "description": "Show or movie name to search for.",
            },
            "action": {"type": "string", "enum": ["search", "play"]},
        },
        "required": ["service"],
    }

    def run(
        self,
        service: str | None = None,
        title: str | None = None,
        action: str = "search",
        **kwargs: Any,
    ) -> str:
        key = _ALIASES.get((service or "").strip().lower())
        if key is None:
            return (
                "I can open Netflix, Prime Video, JioHotstar or YouTube - "
                "which one?"
            )
        label, search_url, home_url = _SERVICES[key]
        title = (title or "").strip()

        # full auto: let the browser driver click through to playback
        if title and action == "play" and browser.available():
            return browser.play(key, title)

        url = search_url.format(q=quote_plus(title)) if title else home_url
        try:
            _start(url)
        except Exception as exc:  # noqa: BLE001
            return f"Couldn't open {label} ({exc})."

        if title:
            return (
                f"Opened {label} search for '{title}' - click the first result "
                f"to start watching."
            )
        return f"Opened {label}."
