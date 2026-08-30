"""Tools Nexa can call: live data (clock, weather) and, later, actions.

The LLM is handed a menu of tool specs. When it decides a question needs one it
returns a structured call; `ToolRegistry` runs it and feeds the result back.
Same mechanism will later carry `open_app`, `run_command`, etc.
"""

from nexa.tools.apps import OpenAppTool
from nexa.tools.base import Tool
from nexa.tools.clock import ClockTool, current_time_string
from nexa.tools.contacts import Contacts
from nexa.tools.registry import ToolRegistry
from nexa.tools.streaming import StreamingTool
from nexa.tools.weather import WeatherTool
from nexa.tools.web import WebSearchTool
from nexa.tools.whatsapp import WhatsAppTool

__all__ = [
    "Tool",
    "ClockTool",
    "current_time_string",
    "Contacts",
    "OpenAppTool",
    "StreamingTool",
    "ToolRegistry",
    "WeatherTool",
    "WebSearchTool",
    "WhatsAppTool",
]
