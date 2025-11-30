"""Fixtures for background task testing"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest


class MockRunBroker:
    """Mock RunBroker for testing"""

    def __init__(self, run_id: str):
        self.run_id = run_id
        self.events: list[tuple[str, Any]] = []
        self.finished = asyncio.Event()
        self._put_calls: list[tuple[str, Any]] = []

    async def put(self, event_id: str, payload: Any) -> None:
        """Record put calls"""
        self._put_calls.append((event_id, payload))
        self.events.append((event_id, payload))
        if isinstance(payload, tuple) and payload[0] == "end":
            self.finished.set()

    async def aiter(self):
        """Yield recorded events"""
        for event in self.events:
            yield event
        self.finished.set()

    def mark_finished(self) -> None:
        self.finished.set()

    def is_finished(self) -> bool:
        return self.finished.is_set()

    def is_empty(self) -> bool:
        return len(self.events) == 0

    def get_age(self) -> float:
        return 0.0


class BackgroundTaskHelper:
    """Helper for testing background tasks"""

    @staticmethod
    async def create_slow_task(duration: float = 0.1):
        """Create a slow async task for testing"""
        await asyncio.sleep(duration)
        return {"status": "completed"}

    @staticmethod
    async def create_failing_task(error_msg: str = "Task failed"):
        """Create a task that fails"""
        await asyncio.sleep(0.01)
        raise RuntimeError(error_msg)

    @staticmethod
    async def create_hanging_task():
        """Create a task that hangs indefinitely"""
        await asyncio.sleep(3600)  # 1 hour

    @staticmethod
    def create_mock_session():
        """Create a mock database session"""
        session = AsyncMock()
        session.execute = AsyncMock()
        session.commit = AsyncMock()
        session.scalar = AsyncMock()
        session.refresh = AsyncMock()
        session.close = AsyncMock()
        return session


@pytest.fixture
def mock_run_broker():
    """Fixture providing a mock RunBroker"""
    return MockRunBroker("test-run-id")


@pytest.fixture
def background_task_helper():
    """Fixture providing background task testing utilities"""
    return BackgroundTaskHelper()


@pytest.fixture
def event_queue():
    """Fixture providing an asyncio Queue for testing"""
    return asyncio.Queue()


@pytest.fixture
async def mock_broker_manager():
    """Fixture providing a mock BrokerManager"""
    manager = MagicMock()
    manager._brokers = {}
    manager.get_or_create_broker = MagicMock(
        side_effect=lambda run_id: MockRunBroker(run_id)
    )
    manager.get_broker = MagicMock(return_value=None)
    manager.cleanup_broker = MagicMock()
    manager.remove_broker = MagicMock()
    return manager
