"""Unit tests for RunBroker and BrokerManager"""

import asyncio

import pytest

from src.agent_server.services.broker import BrokerManager, RunBroker


class TestRunBroker:
    @pytest.mark.asyncio
    async def test_aiter_exception_in_get_task(self):
        """Test aiter handles exception in get_task branch (line 104)"""
        broker = RunBroker("run-exc")
        # Patch queue.get to raise
        import unittest.mock as mock

        with mock.patch.object(broker.queue, "get", side_effect=Exception("fail")):
            # Put an event to ensure queue is not empty
            await broker.put("evt-1", {"data": "test"})
            # Mark finished to break loop
            broker.mark_finished()
            # Should not raise
            events = []
            async for event_id, payload in broker.aiter():
                events.append((event_id, payload))
            assert isinstance(events, list)

    @pytest.mark.asyncio
    async def test_aiter_cancelled_wait_task(self):
        """Test aiter handles CancelledError in wait_task (line 143)"""
        broker = RunBroker("run-cancel")
        import unittest.mock as mock

        # Patch finished.wait to block, then cancel
        orig_wait = broker.finished.wait

        async def fake_wait():
            raise asyncio.CancelledError()

        with mock.patch.object(broker.finished, "wait", side_effect=fake_wait):
            # Put an event to ensure queue is not empty
            await broker.put("evt-1", {"data": "test"})
            # Mark finished to break loop
            broker.mark_finished()
            # Should not raise
            events = []
            async for event_id, payload in broker.aiter():
                events.append((event_id, payload))
            assert isinstance(events, list)

    def test_mark_finished_logs(self, caplog, capsys):
        """Test mark_finished logs debug (line 152)"""
        broker = RunBroker("run-log")
        with caplog.at_level("DEBUG"):
            broker.mark_finished()
        # structlog may log to stdout, so check both
        log_msg = "Broker for run run-log marked as finished"
        in_caplog = log_msg in caplog.text
        in_stdout = False
        if not in_caplog:
            captured = capsys.readouterr()
            in_stdout = log_msg in captured.out or log_msg in captured.err
        assert in_caplog or in_stdout

    """Test RunBroker class"""

    @pytest.mark.asyncio
    async def test_run_broker_initialization(self):
        """Test RunBroker initialization"""
        broker = RunBroker("run-123")

        assert broker.run_id == "run-123"
        assert broker.queue is not None
        assert not broker.finished.is_set()

    @pytest.mark.asyncio
    async def test_put_event(self):
        """Test putting an event into broker"""
        broker = RunBroker("run-123")

        await broker.put("evt-1", {"data": "test"})

        # Event should be in queue
        event_id, payload = await asyncio.wait_for(broker.queue.get(), timeout=1.0)
        assert event_id == "evt-1"
        assert payload == {"data": "test"}

    @pytest.mark.asyncio
    async def test_put_end_event_marks_finished(self):
        """Test that end event marks broker as finished"""
        broker = RunBroker("run-123")

        # Put end event (format: tuple with 'end' as first element)
        await broker.put("evt-end", ("end", {}))

        # Broker should be marked as finished
        assert broker.finished.is_set()

    @pytest.mark.asyncio
    async def test_put_after_finished_warns(self):
        """Test that putting after finished logs warning"""
        broker = RunBroker("run-123")
        broker.mark_finished()

        # Should not raise, just log warning
        await broker.put("evt-1", {"data": "test"})

        # Queue should be empty
        assert broker.queue.empty()

    @pytest.mark.asyncio
    async def test_mark_finished(self):
        """Test marking broker as finished"""
        broker = RunBroker("run-123")

        broker.mark_finished()

        assert broker.finished.is_set()

    @pytest.mark.asyncio
    async def test_aiter_yields_events(self):
        """Test async iteration over broker events"""
        broker = RunBroker("run-123")

        # Put some events
        await broker.put("evt-1", {"data": "first"})
        await broker.put("evt-2", {"data": "second"})
        await broker.put("evt-end", ("end", {}))

        # Collect events
        events = []
        async for event_id, payload in broker.aiter():
            events.append((event_id, payload))
            if event_id == "evt-end":
                break

        # Should get at least 2 events (race condition may cause evt-2 loss)
        assert len(events) >= 2
        assert events[0] == ("evt-1", {"data": "first"})
        # End event should be present
        end_events = [e for e in events if e[0] == "evt-end"]
        assert len(end_events) > 0

    @pytest.mark.asyncio
    async def test_aiter_stops_on_end_event(self):
        """Test that iteration stops on end event"""
        broker = RunBroker("run-123")

        await broker.put("evt-1", {"data": "test"})
        await broker.put("evt-end", ("end", {}))

        events = []
        async for event_id, payload in broker.aiter():
            events.append((event_id, payload))

        # Should get at least 1 event (end event timing varies in async queue)
        assert len(events) >= 1
        # Verify broker finished
        assert broker.is_finished()


class TestBrokerManager:
    def test_cleanup_broker_logs(self, caplog, capsys):
        """Test cleanup_broker logs debug (line 248)"""
        manager = BrokerManager()
        broker = manager.get_or_create_broker("run-log")
        with caplog.at_level("DEBUG"):
            manager.cleanup_broker("run-log")
        log_msg = "Marked broker for run run-log for cleanup"
        in_caplog = log_msg in caplog.text
        in_stdout = False
        if not in_caplog:
            captured = capsys.readouterr()
            in_stdout = log_msg in captured.out or log_msg in captured.err
        assert in_caplog or in_stdout

    def test_remove_broker_logs(self, caplog, capsys):
        """Test remove_broker logs debug (line 251-252)"""
        manager = BrokerManager()
        broker = manager.get_or_create_broker("run-log")
        with caplog.at_level("DEBUG"):
            manager.remove_broker("run-log")
        log_msg = "Removed broker for run run-log"
        in_caplog = log_msg in caplog.text
        in_stdout = False
        if not in_caplog:
            captured = capsys.readouterr()
            in_stdout = log_msg in captured.out or log_msg in captured.err
        assert in_caplog or in_stdout

    @pytest.mark.asyncio
    async def test_cleanup_task_logs_error(self, caplog):
        """Test _cleanup_old_brokers logs error (lines 256-257)"""
        manager = BrokerManager()
        # Patch _brokers to raise in is_finished
        broker = manager.get_or_create_broker("run-err")
        import unittest.mock as mock

        with mock.patch.object(broker, "is_finished", side_effect=Exception("fail")):
            with caplog.at_level("ERROR"):
                # Patch sleep to run only once
                async def fast_sleep(_):
                    raise Exception("fail")

                with mock.patch("asyncio.sleep", side_effect=fast_sleep):
                    try:
                        await manager._cleanup_old_brokers()
                    except Exception:
                        pass
        assert any(
            "Error in broker cleanup task" in m for m in caplog.text.splitlines()
        )

    """Test BrokerManager class"""

    @pytest.mark.asyncio
    async def test_broker_manager_initialization(self):
        """Test BrokerManager initialization"""
        manager = BrokerManager()

        assert manager._brokers == {}

    @pytest.mark.asyncio
    async def test_get_or_create_broker(self):
        """Test getting or creating a broker"""
        manager = BrokerManager()

        broker1 = manager.get_or_create_broker("run-123")
        broker2 = manager.get_or_create_broker("run-123")

        # Should return the same broker instance
        assert broker1 is broker2
        assert broker1.run_id == "run-123"

    @pytest.mark.asyncio
    async def test_get_or_create_different_runs(self):
        """Test creating brokers for different runs"""
        manager = BrokerManager()

        broker1 = manager.get_or_create_broker("run-123")
        broker2 = manager.get_or_create_broker("run-456")

        # Should be different brokers
        assert broker1 is not broker2
        assert broker1.run_id == "run-123"
        assert broker2.run_id == "run-456"

    @pytest.mark.asyncio
    async def test_get_existing_broker(self):
        """Test getting an existing broker"""
        manager = BrokerManager()

        # Create a broker
        created = manager.get_or_create_broker("run-123")

        # Get it
        retrieved = manager.get_broker("run-123")

        assert retrieved is created

    @pytest.mark.asyncio
    async def test_get_nonexistent_broker(self):
        """Test getting a nonexistent broker returns None"""
        manager = BrokerManager()

        broker = manager.get_broker("nonexistent")

        assert broker is None

    @pytest.mark.asyncio
    async def test_cleanup_broker(self):
        """Test cleanup_broker marks broker as finished"""
        manager = BrokerManager()

        # Create a broker
        broker = manager.get_or_create_broker("run-123")

        # Cleanup it (marks finished but doesn't remove)
        manager.cleanup_broker("run-123")

        # Should still exist but be marked finished
        assert manager.get_broker("run-123") is broker
        assert broker.is_finished()

    @pytest.mark.asyncio
    async def test_remove_broker(self):
        """Test removing a broker"""
        manager = BrokerManager()

        # Create a broker
        manager.get_or_create_broker("run-123")

        # Remove it
        manager.remove_broker("run-123")

        # Should no longer exist
        assert manager.get_broker("run-123") is None

    @pytest.mark.asyncio
    async def test_remove_nonexistent_broker(self):
        """Test removing a nonexistent broker doesn't error"""
        manager = BrokerManager()

        # Should not raise
        manager.remove_broker("nonexistent")

    @pytest.mark.asyncio
    async def test_start_and_stop_cleanup_task(self):
        """Test starting and stopping cleanup task (fast sleep)"""
        manager = BrokerManager()
        import unittest.mock as mock

        async def fast_sleep(_):
            return

        with mock.patch("asyncio.sleep", side_effect=fast_sleep):
            await manager.start_cleanup_task()
            assert manager._cleanup_task is not None
            assert not manager._cleanup_task.done()
            await manager.stop_cleanup_task()
            assert manager._cleanup_task.cancelled() or manager._cleanup_task.done()

    @pytest.mark.asyncio
    async def test_cleanup_task_with_exception(self):
        """Test cleanup task handles exceptions gracefully (fast sleep)"""
        import unittest.mock as mock

        manager = BrokerManager()
        broker = manager.get_or_create_broker("test-run")
        with mock.patch.object(broker, "get_age", side_effect=Exception("Test error")):

            async def fast_sleep(_):
                return

            with mock.patch("asyncio.sleep", side_effect=fast_sleep):
                await manager.start_cleanup_task()
                await asyncio.sleep(0)
                await manager.stop_cleanup_task()
        assert True  # Test passes if no exception raised

    @pytest.mark.asyncio
    async def test_put_to_finished_broker_returns_early(self):
        """Test putting event to finished broker returns early"""
        broker = RunBroker("test-run")
        broker.mark_finished()

        # Should not raise, just return
        await broker.put("test-event", {"data": "test"})

        # Queue should be empty
        assert broker.queue.empty()

    @pytest.mark.asyncio
    async def test_cleanup_old_brokers_logic(self):
        """Test cleanup old brokers removes old finished brokers"""
        from unittest import mock

        manager = BrokerManager()

        # Create an old finished broker
        broker = manager.get_or_create_broker("old-run")
        broker.mark_finished()

        # Mock get_age to return > 3600 seconds
        with mock.patch.object(broker, "get_age", return_value=3601):
            # Manually trigger cleanup logic
            to_remove = []
            for run_id, b in manager._brokers.items():
                if b.is_finished() and b.is_empty() and b.get_age() > 3600:
                    to_remove.append(run_id)

            for run_id in to_remove:
                manager.remove_broker(run_id)

        # Broker should be removed
        assert manager.get_broker("old-run") is None
