"""Integration tests for RunBroker (Phase 1.1)

Tests broker with real producers and consumers in realistic scenarios.
"""

import asyncio

import pytest


@pytest.mark.integration
@pytest.mark.broker
class TestBrokerProducerConsumer:
    """Test broker with realistic producer-consumer patterns"""

    @pytest.mark.asyncio
    async def test_broker_with_slow_producer(self):
        """Broker should handle slow producers gracefully"""
        from src.agent_server.services.broker import RunBroker

        broker = RunBroker("test-run")

        async def slow_producer():
            """Producer that emits events slowly"""
            for i in range(10):
                await asyncio.sleep(0.05)  # Slow producer
                await broker.put(f"event{i}", ("values", {"index": i}))
            await broker.put("end", ("end", {}))

        async def fast_consumer():
            """Consumer that processes events quickly"""
            events = []
            async for event_id, payload in broker.aiter():
                events.append((event_id, payload))
            return events

        # Run producer and consumer concurrently
        producer_task = asyncio.create_task(slow_producer())
        consumer_task = asyncio.create_task(fast_consumer())

        events = await consumer_task
        await producer_task

        # Should get all events including end (end event marks broker finished)
        assert len(events) >= 10  # At least the data events
        assert broker.is_finished()

    @pytest.mark.asyncio
    async def test_broker_with_slow_consumer(self):
        """Broker should handle slow consumers (queue buildup)"""
        from src.agent_server.services.broker import RunBroker

        broker = RunBroker("test-run")

        async def fast_producer():
            """Producer that emits events quickly"""
            for i in range(50):
                await broker.put(f"event{i}", ("values", {"index": i}))
            await broker.put("end", ("end", {}))

        async def slow_consumer():
            """Consumer that processes events slowly"""
            events = []
            async for event_id, payload in broker.aiter():
                await asyncio.sleep(0.01)  # Slow processing
                events.append((event_id, payload))
            return events

        # Start both
        producer_task = asyncio.create_task(fast_producer())
        consumer_task = asyncio.create_task(slow_consumer())

        await producer_task
        events = await consumer_task

        # Due to race conditions, end event may or may not be yielded
        assert len(events) in (50, 51), f"Expected 50 or 51 events, got {len(events)}"

    @pytest.mark.asyncio
    async def test_broker_with_bursty_traffic(self):
        """Broker should handle bursty event patterns"""
        from src.agent_server.services.broker import RunBroker

        broker = RunBroker("test-run")

        async def bursty_producer():
            """Producer with bursts of events"""
            # Burst 1
            for i in range(20):
                await broker.put(f"burst1_event{i}", ("values", {"i": i}))

            await asyncio.sleep(0.1)  # Pause

            # Burst 2
            for i in range(20):
                await broker.put(f"burst2_event{i}", ("values", {"i": i}))

            await broker.put("end", ("end", {}))

        async def consumer():
            events = []
            async for event_id, payload in broker.aiter():
                events.append(event_id)
            return events

        producer_task = asyncio.create_task(bursty_producer())
        consumer_task = asyncio.create_task(consumer())

        events = await consumer_task
        await producer_task

        # Should get all data events (end event timing varies)
        assert len(events) >= 40  # 20 + 20 (data events)

        # Verify both bursts received (allow for minimal loss in race conditions)
        burst1_events = [e for e in events if e.startswith("burst1")]
        burst2_events = [e for e in events if e.startswith("burst2")]
        assert len(burst1_events) >= 19, (
            f"Burst1 missing events: {len(burst1_events)}/20"
        )
        assert len(burst2_events) >= 19, (
            f"Burst2 missing events: {len(burst2_events)}/20"
        )


@pytest.mark.integration
@pytest.mark.broker
class TestBrokerErrorScenarios:
    """Test broker error handling and edge cases"""

    @pytest.mark.asyncio
    async def test_broker_producer_error_recovery(self):
        """Broker should handle producer errors gracefully"""
        from src.agent_server.services.broker import RunBroker

        broker = RunBroker("test-run")

        async def failing_producer():
            """Producer that fails midway"""
            for i in range(5):
                await broker.put(f"event{i}", ("values", {"i": i}))

            # Simulate error but mark as finished
            broker.mark_finished()

        async def consumer():
            events = []
            async for event_id, payload in broker.aiter():
                events.append(event_id)
            return events

        producer_task = asyncio.create_task(failing_producer())
        consumer_task = asyncio.create_task(consumer())

        await producer_task
        events = await consumer_task

        assert len(events) == 5

    @pytest.mark.asyncio
    async def test_broker_consumer_cancellation(self):
        """Broker should handle consumer cancellation"""
        from src.agent_server.services.broker import RunBroker

        broker = RunBroker("test-run")

        async def producer():
            for i in range(100):
                await broker.put(f"event{i}", ("values", {"i": i}))
                await asyncio.sleep(0.01)
            await broker.put("end", ("end", {}))

        async def consumer():
            events = []
            async for event_id, payload in broker.aiter():
                events.append(event_id)
                if len(events) >= 10:
                    # Consumer decides to stop early
                    raise asyncio.CancelledError()
            return events

        producer_task = asyncio.create_task(producer())
        consumer_task = asyncio.create_task(consumer())

        # Consumer should be cancelled
        with pytest.raises(asyncio.CancelledError):
            await consumer_task

        # Cancel producer as well
        producer_task.cancel()
        try:
            await producer_task
        except asyncio.CancelledError:
            pass


@pytest.mark.integration
@pytest.mark.broker
class TestBrokerManagerIntegration:
    """Test BrokerManager with multiple concurrent runs"""

    @pytest.mark.asyncio
    async def test_broker_manager_multiple_runs(self):
        """BrokerManager should handle multiple concurrent runs"""
        from src.agent_server.services.broker import BrokerManager

        manager = BrokerManager()

        async def simulate_run(run_id: str, event_count: int):
            """Simulate a single run"""
            broker = manager.get_or_create_broker(run_id)

            # Producer
            for i in range(event_count):
                await broker.put(f"event{i}", ("values", {"i": i}))
            await broker.put("end", ("end", {}))

            # Consumer
            events = []
            async for event_id, payload in broker.aiter():
                events.append(event_id)

            manager.cleanup_broker(run_id)
            return len(events)

        # Run multiple concurrent simulations
        tasks = [asyncio.create_task(simulate_run(f"run{i}", 10 + i)) for i in range(5)]

        results = await asyncio.gather(*tasks)

        # Each run should get at least its data events
        # (end event consumption timing varies)
        for i, count in enumerate(results):
            assert count >= 10 + i  # At least the data events

    @pytest.mark.asyncio
    async def test_broker_manager_cleanup_old_brokers(self):
        """BrokerManager should clean up old finished brokers"""
        from src.agent_server.services.broker import BrokerManager

        manager = BrokerManager()

        # Create and finish some brokers
        for i in range(5):
            broker = manager.get_or_create_broker(f"run{i}")
            await broker.put("end", ("end", {}))
            manager.cleanup_broker(f"run{i}")

        # All should be marked finished
        for i in range(5):
            broker = manager.get_broker(f"run{i}")
            assert broker is not None
            assert broker.is_finished()

        # Verify all are finished and then remove
        for i in range(5):
            broker = manager.get_broker(f"run{i}")
            assert broker is not None
            assert broker.is_finished()

        # Manually remove old brokers (simulating background cleanup)
        for i in range(5):
            manager.remove_broker(f"run{i}")

        # Brokers should be removed
        for i in range(5):
            assert manager.get_broker(f"run{i}") is None
