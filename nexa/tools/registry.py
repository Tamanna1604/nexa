"""Holds the available tools, exposes their specs, dispatches calls."""

from __future__ import annotations

from typing import Any

from nexa.tools.base import Tool


class ToolRegistry:
    def __init__(self, tools: list[Tool] | None = None) -> None:
        self._tools: dict[str, Tool] = {t.name: t for t in (tools or [])}

    def __bool__(self) -> bool:
        return bool(self._tools)

    def names(self) -> list[str]:
        return list(self._tools)

    def specs(self) -> list[dict[str, Any]]:
        """All tool definitions, in Groq/OpenAI `tools` format."""
        return [t.spec() for t in self._tools.values()]

    def run(self, name: str, arguments: dict[str, Any] | None) -> str:
        """Execute one tool call. Never raises - failures come back as text so
        the model can react to them."""
        tool = self._tools.get(name)
        if tool is None:
            return f"[error: no tool named {name!r}]"
        try:
            return tool.run(**(arguments or {}))
        except Exception as exc:  # noqa: BLE001
            return f"[error running {name}: {exc}]"
