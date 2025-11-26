from __future__ import annotations
from pydantic import BaseModel, Field


class ThinkToolParams(BaseModel):
    """
    Use the tool to think about something.
    It will not obtain new information or change the database, but just append the thought to the log.
    Use it when complex reasoning or some cache memory is needed.
    """

    thought: str = Field(..., description="A thought to think about.")
