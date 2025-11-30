"""Database session helpers for background tasks.

Provides utilities for short-lived database sessions that prevent
connection pool exhaustion and transaction timeouts.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from .orm import Run as RunORM
from .orm import Thread as ThreadORM
from .orm import _get_session_maker
from .serializers import GeneralSerializer

logger = structlog.get_logger(__name__)
serializer = GeneralSerializer()


@asynccontextmanager
async def get_short_session() -> AsyncIterator[AsyncSession]:
    """Get a short-lived database session for single operations.

    This should be used for atomic database operations in background tasks
    instead of holding a session for the entire task lifetime.

    Example:
        async with get_short_session() as session:
            await session.execute(...)
            await session.commit()
    """
    maker = _get_session_maker()
    async with maker() as session:
        try:
            yield session
        except Exception as e:
            await session.rollback()
            logger.error(f"Session error, rolled back: {e}")
            raise
        finally:
            await session.close()


async def update_run_in_db(
    run_id: str,
    status: str | None = None,
    output: dict | None = None,
    error_message: str | None = None,
) -> None:
    """Update run record in database with short-lived session.

    Args:
        run_id: Run ID to update
        status: Optional new status
        output: Optional output data
        error_message: Optional error message
    """
    async with get_short_session() as session:
        values: dict[str, Any] = {"updated_at": datetime.now(UTC)}

        if status is not None:
            values["status"] = status
        if output is not None:
            # Serialize output to ensure JSON compatibility
            try:
                serialized_output = serializer.serialize(output)
                values["output"] = serialized_output
            except Exception as e:
                logger.warning(f"Failed to serialize output for run {run_id}: {e}")
                values["output"] = {
                    "error": "Output serialization failed",
                    "original_type": str(type(output)),
                }
        if error_message is not None:
            values["error_message"] = error_message

        await session.execute(
            update(RunORM).where(RunORM.run_id == run_id).values(**values)
        )
        await session.commit()

        logger.debug(f"Updated run {run_id} in database", status=status)


async def update_thread_in_db(
    thread_id: str,
    status: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Update thread record in database with short-lived session.

    Args:
        thread_id: Thread ID to update
        status: Optional new status
        metadata: Optional metadata to merge
    """
    async with get_short_session() as session:
        values: dict[str, Any] = {"updated_at": datetime.now(UTC)}

        if status is not None:
            values["status"] = status
        if metadata is not None:
            # For metadata, we need to read-modify-write
            from sqlalchemy import select

            thread = await session.scalar(
                select(ThreadORM).where(ThreadORM.thread_id == thread_id)
            )
            if thread:
                existing_metadata = dict(thread.metadata_json or {})
                existing_metadata.update(metadata)
                values["metadata_json"] = existing_metadata

        await session.execute(
            update(ThreadORM).where(ThreadORM.thread_id == thread_id).values(**values)
        )
        await session.commit()

        logger.debug(f"Updated thread {thread_id} in database", status=status)


async def get_run_from_db(run_id: str) -> RunORM | None:
    """Get run record from database with short-lived session.

    Args:
        run_id: Run ID to fetch

    Returns:
        RunORM instance or None if not found
    """
    async with get_short_session() as session:
        from sqlalchemy import select

        result = await session.scalar(select(RunORM).where(RunORM.run_id == run_id))
        if result:
            # Refresh to ensure latest data
            await session.refresh(result)
        return result


async def get_thread_from_db(thread_id: str) -> ThreadORM | None:
    """Get thread record from database with short-lived session.

    Args:
        thread_id: Thread ID to fetch

    Returns:
        ThreadORM instance or None if not found
    """
    async with get_short_session() as session:
        from sqlalchemy import select

        result = await session.scalar(
            select(ThreadORM).where(ThreadORM.thread_id == thread_id)
        )
        if result:
            await session.refresh(result)
        return result
