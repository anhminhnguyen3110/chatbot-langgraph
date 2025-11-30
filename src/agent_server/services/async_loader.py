"""Async module loader with configurable initialization strategies"""

import importlib.util
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class AsyncModuleLoader:
    """Handles dynamic loading of modules with configurable async initialization"""

    _async_loaders: dict[str, Callable[[Any, str], Awaitable[None]]] = {}

    @classmethod
    def register_loaders_from_config(cls, loaders_config: dict[str, str]):
        """Register loaders from config: {"name": "module.path:function_name"}"""
        for name, path in loaders_config.items():
            try:
                module_path, func_name = path.split(":", 1)
                module = importlib.import_module(module_path)
                cls._async_loaders[name] = getattr(module, func_name)
                logger.info(f"✅ Registered loader '{name}' from {path}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to register loader '{name}': {e}")

    @classmethod
    async def load_module_from_file(
        cls,
        graph_id: str,
        file_path: Path,
        export_name: str,
        async_loaders: list[str] | None = None,
    ) -> Any:
        """Load graph module, run async loaders, call post-load hook, return graph"""
        if not file_path.exists():
            raise ValueError(f"Graph file not found: {file_path}")

        module_name = f"graphs.{graph_id}"
        spec = importlib.util.spec_from_file_location(
            module_name, str(file_path.resolve())
        )
        if not spec or not spec.loader:
            raise ValueError(f"Failed to load graph module: {file_path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        if async_loaders:
            await cls._run_async_loaders(module, graph_id, async_loaders)

        if hasattr(module, "__post_async_load__") and callable(
            module.__post_async_load__
        ):
            module.__post_async_load__()

        if not hasattr(module, export_name):
            raise ValueError(f"Graph export '{export_name}' not found in {file_path}")

        return getattr(module, export_name)

    @classmethod
    async def _run_async_loaders(
        cls, module: Any, graph_id: str, loader_names: list[str]
    ):
        """Run specified async loaders for the module"""
        for name in loader_names:
            if name in cls._async_loaders:
                try:
                    await cls._async_loaders[name](module, graph_id)
                except Exception as e:
                    logger.warning(f"⚠️ Loader '{name}' failed for '{graph_id}': {e}")
            else:
                logger.warning(f"⚠️ Async loader '{name}' not registered")
