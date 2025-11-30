"""Unit tests for broker backpressure functionality"""

import asyncio

import pytest

from src.agent_server.services.broker import BackpressureError, RunBroker


@pytest.mark.unit
@pytest.mark.broker
class TestBackpressure:
    """Test backpressure mechanisms"""

    @pytest.mark.asyncio
    async def test_queue_size_limit(self):
        """Queue should have configurable size limit"""
        broker = RunBroker("test_run", maxsize=10)

        # Fill queue to capacity
        for i in range(10):
            await broker.put(f"event_{i}", ("data", {"value": i}), timeout=0.1)

        # Next put should timeout due to full queue
        with pytest.raises(BackpressureError) as exc_info:
            await broker.put("event_overflow", ("data", {"value": 999}), timeout=0.1)

        assert "Queue full" in str(exc_info.value)
        assert broker.get_queue_size() == 10

    @pytest.mark.asyncio
    async def test_backpressure_with_consumer(self):
        """Backpressure should not trigger when consumer drains queue"""
        broker = RunBroker("test_run", maxsize=5)
        events_received = []

        async def consumer():
            async for event_id, payload in broker.aiter():
                events_received.append(event_id)
                await asyncio.sleep(0.01)  # Simulate processing

        consumer_task = asyncio.create_task(consumer())

        # Produce events - should not block because consumer is draining
        for i in range(10):
            await broker.put(f"event_{i}", ("data", {"value": i}), timeout=1.0)

        await broker.put("end_event", ("end", {}), timeout=1.0)
        await consumer_task

        # Should receive at least 10 events (end event stops iteration immediately)
        assert len(events_received) >= 10
        assert events_received[0] == "event_0"

    @pytest.mark.asyncio
    async def test_slow_consumer_warning(self):
        """Should detect and warn about slow consumers"""
        broker = RunBroker("test_run", maxsize=2000)
        broker._slow_consumer_threshold = 10  # Low threshold for testing

        # Fill queue beyond threshold
        for i in range(15):
            await broker.put(f"event_{i}", ("data", {"value": i}), timeout=1.0)

        # Lag should exceed threshold
        lag = broker.get_lag()
        assert lag > 10, f"Expected lag > 10, got {lag}"

    @pytest.mark.asyncio
    async def test_consumer_lag_tracking(self):
        """Should accurately track consumer lag"""
        broker = RunBroker("test_run", maxsize=100)

        # Produce 10 events
        for i in range(10):
            await broker.put(f"event_{i}", ("data", {"value": i}))

        assert broker.get_lag() == 10
        assert broker._total_events == 10
        assert broker._consumed_events == 0

        # Consume 3 events
        count = 0
        async for event_id, payload in broker.aiter():
            count += 1
            if count == 3:
                break

        assert broker.get_lag() == 7  # 10 - 3
        assert broker._consumed_events == 3

    @pytest.mark.asyncio
    async def test_backpressure_with_timeout_none(self):
        """Put with timeout=None should wait forever"""
        broker = RunBroker("test_run", maxsize=2)

        # Fill queue
        await broker.put("event_1", ("data", {}), timeout=None)
        await broker.put("event_2", ("data", {}), timeout=None)

        # Start consumer to drain queue
        async def drain():
            await asyncio.sleep(0.1)  # Let put block first
            async for _ in broker.aiter():
                pass

        drain_task = asyncio.create_task(drain())

        # This should eventually succeed (wait for drain)
        await broker.put("event_3", ("data", {}), timeout=None)
        await broker.put("end", ("end", {}), timeout=None)

        await drain_task
        assert broker._total_events == 4

    @pytest.mark.asyncio
    async def test_queue_metrics(self):
        """Should provide queue metrics"""
        broker = RunBroker("test_run", maxsize=100)

        # Initial state
        assert broker.get_queue_size() == 0
        assert broker.get_lag() == 0

        # Add events
        for i in range(5):
            await broker.put(f"event_{i}", ("data", {}))

        assert broker.get_queue_size() == 5
        assert broker.get_lag() == 5

        # Consume 2
        count = 0
        async for _ in broker.aiter():
            count += 1
            if count == 2:
                break

        assert broker.get_queue_size() == 3
        assert broker.get_lag() == 3


@pytest.mark.unit
@pytest.mark.broker
class TestBackpressureEdgeCases:
    """Test edge cases in backpressure handling"""

    @pytest.mark.asyncio
    async def test_put_to_finished_broker_no_error(self):
        """Putting to finished broker should not raise BackpressureError"""
        broker = RunBroker("test_run", maxsize=10)
        broker.mark_finished()

        # Should log warning but not raise
        await broker.put("event_1", ("data", {}), timeout=0.1)
        assert broker._total_events == 0  # Not counted

    @pytest.mark.asyncio
    async def test_end_event_marks_finished(self):
        """End event should mark broker as finished"""
        broker = RunBroker("test_run", maxsize=10)

        await broker.put("event_1", ("data", {}))
        assert not broker.is_finished()

        await broker.put("end_event", ("end", {}))
        assert broker.is_finished()

    @pytest.mark.asyncio
    async def test_concurrent_producers_backpressure(self):
        """Multiple producers should all respect backpressure"""
        broker = RunBroker("test_run", maxsize=5)
        errors = []

        async def producer(producer_id: int):
            try:
                for i in range(10):
                    await broker.put(f"p{producer_id}_e{i}", ("data", {}), timeout=0.05)
            except BackpressureError as e:
                errors.append(e)

        # Start 3 producers competing for limited queue
        producers = [asyncio.create_task(producer(i)) for i in range(3)]
        await asyncio.gather(*producers, return_exceptions=True)

        # Should have backpressure errors
        assert len(errors) > 0, "Expected backpressure errors from concurrent producers"
        assert broker.get_queue_size() <= 5
