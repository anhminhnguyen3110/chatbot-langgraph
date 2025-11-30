from __future__ import annotations

from langchain_core.tools import BaseTool, StructuredTool

__tool_registry: dict[str, StructuredTool] = {}


def add_tool(tool_name: str, tool: StructuredTool):
    __tool_registry[tool_name] = tool


def has_tool(tool_name: str) -> bool:
    return tool_name in __tool_registry


def get_all_tool() -> list[BaseTool]:
    return list(__tool_registry.values())
