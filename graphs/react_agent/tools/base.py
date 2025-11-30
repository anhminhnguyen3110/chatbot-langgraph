from __future__ import annotations

from abc import ABC
from typing import Any

from langchain_core.tools import BaseTool
from pydantic import Field


class AppTool(BaseTool, ABC):
    name: str = Field(..., description="Tên tool")
    description: str = Field(..., description="Mô tả công dụng tool")
    timeout: float | None = Field(
        default=None,
        description="Timeout (giây) cho một lần chạy tool. None = không giới hạn.",
    )

    def _run(self, *args: Any, **kwargs: Any) -> str:
        """Sync implementation. Bắt buộc override ở lớp con."""
        raise NotImplementedError

    async def _arun(self, *args: Any, **kwargs: Any) -> str:
        """Async implementation. Bắt buộc override ở lớp con."""
        raise NotImplementedError
