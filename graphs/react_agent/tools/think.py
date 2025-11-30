from __future__ import annotations

from langchain_core.tools import tool

from .params import ThinkToolParams
from .tool_registry import add_tool


def register():
    add_tool("think", think)


@tool(args_schema=ThinkToolParams)
def think(thought: str):
    """Think about something and append it to the log."""
    return thought
