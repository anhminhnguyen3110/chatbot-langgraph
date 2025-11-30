from __future__ import annotations

import os
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient

MCP_URL = os.getenv("AML_MCP_URL", "http://localhost:5000/mcp")
MCP_SERVER_NAME = os.getenv("AML_MCP_SERVER_NAME", "aml-mcp")


def create_mcp_client() -> MultiServerMCPClient:
    client = MultiServerMCPClient(
        {
            MCP_SERVER_NAME: {
                "url": MCP_URL,
                "transport": "streamable_http",
            }
        }
    )
    return client


async def get_mcp_tools_async():
    """Async function to get MCP tools"""

    mcp_client = create_mcp_client()

    try:
        tools = await mcp_client.get_tools()
        return tools
    except Exception as e:
        print(f"[MCP] Failed to get tools: {e}")
        return []


async def load_mcp_tools(module: Any, graph_id: str):
    """Async loader function called by AsyncModuleLoader"""
    mcp_tools = await get_mcp_tools_async()
    if mcp_tools and hasattr(module, "all_tools"):
        local_tools = getattr(module, "local_tools", [])
        module.all_tools = [*local_tools, *mcp_tools]
        print(f"[MCP] ✅ Loaded {len(mcp_tools)} MCP tools for '{graph_id}'")
