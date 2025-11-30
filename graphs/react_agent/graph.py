import asyncio
import os
import json

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain.agents.middleware import (
    SummarizationMiddleware,
    ModelCallLimitMiddleware,
    ToolCallLimitMiddleware,
    ModelFallbackMiddleware,
    TodoListMiddleware,
    ContextEditingMiddleware,
    ClearToolUsesEdit,
    ToolRetryMiddleware,
)

from react_agent.tools.tool_registry import get_all_tool
from react_agent.tools import register_all_local_tools

load_dotenv()

# Gemini API
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PRIMARY_MODEL_ID = os.getenv("PRIMARY_MODEL_ID", "gemini-2.5-flash")
FALLBACK_MODEL_ID = os.getenv("FALLBACK_MODEL_ID", "gemini-2.0-flash")

if not GEMINI_API_KEY:
    raise RuntimeError("Missing GEMINI_API_KEY")

# Load local tools only - MCP tools will be added by async_loader
register_all_local_tools()
local_tools = get_all_tool()
all_tools = local_tools  # Direct reference, will be replaced by async_loader

# Models
primary_model = init_chat_model(
    model=PRIMARY_MODEL_ID,
    model_provider="google_genai",
    api_key=GEMINI_API_KEY,
    temperature=0.7,
    max_tokens=4096,
    streaming=False,
)

fallback_model = init_chat_model(
    model=FALLBACK_MODEL_ID,
    model_provider="google_genai",
    api_key=GEMINI_API_KEY,
    temperature=0.7,
    max_tokens=4096,
    streaming=False,
)

# Middleware
middlewares = [
    SummarizationMiddleware(
        model=fallback_model,
        max_tokens_before_summary=30000,
    ),
    ModelCallLimitMiddleware(thread_limit=50, run_limit=20, exit_behavior="end"),
    ToolCallLimitMiddleware(thread_limit=20, run_limit=20, exit_behavior="continue"),
    ModelFallbackMiddleware(fallback_model),
    TodoListMiddleware(),
    ToolRetryMiddleware(
        max_retries=3,
        backoff_factor=2.0,
        initial_delay=1.0,
    ),
    ContextEditingMiddleware(
        edits=[
            ClearToolUsesEdit(
                trigger=2000,
                keep=3,
                clear_tool_inputs=False,
                placeholder="[cleared]",
            ),
        ]
    ),
]


def _create_agent():
    """Create agent with current tools. Called after async loaders complete."""
    import sys

    current_module = sys.modules[__name__]
    tools = getattr(current_module, "all_tools", local_tools)

    return create_agent(
        model=primary_model,
        tools=tools,
        middleware=middlewares,
    )


def __post_async_load__():
    global agent
    agent = _create_agent()


agent = None
