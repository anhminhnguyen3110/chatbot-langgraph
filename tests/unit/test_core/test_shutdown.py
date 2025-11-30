"""Unit tests for graceful shutdown manager"""

import asyncio
import contextlib

import pytest

from src.agent_server.core.shutdown import ShutdownManager


@pytest.mark.unit
class TestShutdownManager:
    """Test shutdown manager functionality"""

    @pytest.mark.asyncio
    async def test_register_and_unregister_task(self):
        """Should register and unregister tasks"""
        manager = ShutdownManager()

        async def dummy_task():
            await asyncio.sleep(1)

        task = asyncio.create_task(dummy_task())

        # Register
        manager.register_task("task_1", task)
        assert manager.get_active_task_count() == 1
        assert "task_1" in manager.get_active_task_ids()

        # Unregister
        manager.unregister_task("task_1")
        assert manager.get_active_task_count() == 0
        assert "task_1" not in manager.get_active_task_ids()

        task.cancel()
        import contextlib

        with contextlib.suppress(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio
    async def test_shutdown_cancels_tasks(self):
        """Shutdown should cancel all tracked tasks"""
        manager = ShutdownManager(shutdown_timeout=2.0)

        async def long_task():
            await asyncio.sleep(10)

        # Register 3 tasks
        tasks = []
        for i in range(3):
            task = asyncio.create_task(long_task())
            manager.register_task(f"task_{i}", task)
            tasks.append(task)

        assert manager.get_active_task_count() == 3

        # Shutdown should cancel all
        await manager.shutdown()

        assert manager.get_active_task_count() == 0

        # All tasks should be done (cancelled)
        for task in tasks:
            assert task.done()

    @pytest.mark.asyncio
    async def test_shutdown_waits_for_completion(self):
        """Shutdown should wait for tasks with return_exceptions=True"""
        manager = ShutdownManager(shutdown_timeout=2.0)

        async def quick_task():
            await asyncio.sleep(0.1)

        # Register 2 tasks
        for i in range(2):
            task = asyncio.create_task(quick_task())
            manager.register_task(f"task_{i}", task)

        # Shutdown should complete all tasks
        await manager.shutdown()

        # All tasks should be done
        assert manager.get_active_task_count() == 0

    @pytest.mark.asyncio
    async def test_shutdown_timeout(self):
        """Shutdown should handle slow tasks"""
        manager = ShutdownManager(shutdown_timeout=0.2)

        async def slow_task():
            await asyncio.sleep(10)

        task = asyncio.create_task(slow_task())
        manager.register_task("slow_task", task)

        # Should complete (cancel task immediately)
        await manager.shutdown()

        # Task should be cancelled
        assert task.done()
        assert manager.get_active_task_count() == 0

    @pytest.mark.asyncio
    async def test_is_shutting_down(self):
        """Should track shutdown state"""
        manager = ShutdownManager()

        assert not manager.is_shutting_down()

        async def quick_task():
            await asyncio.sleep(0.1)

        task = asyncio.create_task(quick_task())
        manager.register_task("task_1", task)

        # Start shutdown
        shutdown_task = asyncio.create_task(manager.shutdown())

        # Give it a moment
        await asyncio.sleep(0.05)

        assert manager.is_shutting_down()

        await shutdown_task

    @pytest.mark.asyncio
    async def test_empty_shutdown(self):
        """Shutdown with no tasks should complete immediately"""
        manager = ShutdownManager()

        start = asyncio.get_event_loop().time()
        await manager.shutdown()
        elapsed = asyncio.get_event_loop().time() - start

        # Should be instant
        assert elapsed < 0.1

    @pytest.mark.asyncio
    async def test_multiple_shutdowns(self):
        """Multiple shutdown calls should be safe"""
        manager = ShutdownManager()

        async def dummy_task():
            await asyncio.sleep(0.1)

        task = asyncio.create_task(dummy_task())
        manager.register_task("task_1", task)

        # First shutdown
        await manager.shutdown()

        # Second shutdown should be no-op
        await manager.shutdown()

        assert manager.get_active_task_count() == 0

    @pytest.mark.asyncio
    async def test_task_count_tracking(self):
        """Should accurately track task count"""
        manager = ShutdownManager()

        async def dummy_task():
            await asyncio.sleep(0.1)

        assert manager.get_active_task_count() == 0

        # Add 5 tasks
        tasks = []
        for i in range(5):
            task = asyncio.create_task(dummy_task())
            manager.register_task(f"task_{i}", task)
            tasks.append(task)

        assert manager.get_active_task_count() == 5

        # Unregister 2
        manager.unregister_task("task_0")
        manager.unregister_task("task_1")

        assert manager.get_active_task_count() == 3

        # Shutdown rest
        await manager.shutdown()

        assert manager.get_active_task_count() == 0

        # Cancel remaining
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                if not task.done():
                    task.cancel()
                    await task

    @pytest.mark.asyncio
    async def test_get_active_task_ids(self):
        """Should return list of active task IDs"""
        manager = ShutdownManager()

        async def dummy_task():
            await asyncio.sleep(0.1)

        # Register tasks
        for i in range(3):
            task = asyncio.create_task(dummy_task())
            manager.register_task(f"run_{i}", task)

        task_ids = manager.get_active_task_ids()

        assert len(task_ids) == 3
        assert "run_0" in task_ids
        assert "run_1" in task_ids
        assert "run_2" in task_ids

        await manager.shutdown()


@pytest.mark.unit
class TestShutdownManagerSignals:
    """Test signal handling (mocked)"""

    def test_install_signal_handlers(self):
        """Should install signal handlers"""
        manager = ShutdownManager()

        # Should not be installed initially
        assert not manager._signal_handlers_installed

        # Install
        manager.install_signal_handlers()

        assert manager._signal_handlers_installed

        # Multiple installs should be safe
        manager.install_signal_handlers()
        assert manager._signal_handlers_installed
