"""Current date / time. No network - just the system clock."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - py<3.9
    ZoneInfo = None  # type: ignore

from nexa.tools.base import Tool


def _now(tz: str | None):
    if tz and ZoneInfo is not None:
        try:
            return datetime.now(ZoneInfo(tz))
        except Exception:
            pass
    return datetime.now().astimezone()


def current_time_string(tz: str | None = None) -> str:
    """e.g. 'Friday, 29 August 2026, 03:42 PM IST'. Used in the system prompt too."""
    return _now(tz).strftime("%A, %d %B %Y, %I:%M %p %Z").strip()


class ClockTool(Tool):
    name = "get_datetime"
    description = (
        "Get the current local date, time and day of week. Use it for any "
        "question about what time/day/date it is, and to work out relative dates "
        "like 'tomorrow' or 'in 3 hours'."
    )
    parameters = {
        "type": "object",
        "properties": {
            "offset_hours": {
                "type": "number",
                "description": "Optional. Shift the answer this many hours from now (negative for the past).",
            }
        },
        "required": [],
    }

    def __init__(self, tz: str | None = None) -> None:
        self._tz = tz

    def run(self, offset_hours: float | int = 0, **kwargs: Any) -> str:
        when = _now(self._tz) + timedelta(hours=float(offset_hours or 0))
        return when.strftime("%A, %d %B %Y, %I:%M %p %Z").strip()
