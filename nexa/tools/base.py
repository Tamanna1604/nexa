"""The Tool interface + the OpenAI 'function' spec it produces."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Tool(ABC):
    #: short, lowercase, snake_case - the name the model calls
    name: str
    #: one or two sentences telling the model WHEN to use this
    description: str
    #: JSON Schema for the arguments (an object). Empty = no args.
    parameters: dict[str, Any] = {"type": "object", "properties": {}, "required": []}

    @abstractmethod
    def run(self, **kwargs: Any) -> str:
        """Do the thing. Return a short plain-text result for the model to read."""

    def spec(self) -> dict[str, Any]:
        """The tool definition in the shape Groq / OpenAI expect."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
