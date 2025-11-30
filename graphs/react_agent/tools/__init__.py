from __future__ import annotations

from .mcp import create_mcp_client
from .think import register as register_think
from .tool_registry import add_tool, get_all_tool, has_tool


def register_all_local_tools():
    register_think()


__all__ = [
    "register_all_local_tools",
    "add_tool",
    "has_tool",
    "get_all_tool",
    "create_mcp_client",
]
