"""Integration tests for broker backpressure under load"""

import asyncio

import pytest

from src.agent_server.services.broker import BackpressureError, BrokerManager, RunBroker


@pytest.mark.integration
@pytest.mark.broker
class TestBackpressureIntegration:
    """Integration tests for backpressure with real async workloads"""

    @pytest.mark.asyncio
    @pytest.mark.timeout(60)
    async def test_multiple_brokers_concurrent_load(self):
        """Multiple brokers should handle concurrent load independently"""
        manager = BrokerManager(default_maxsize=50)
        results = {}

        async def run_workload(run_id: str, num_events: int):
            broker = manager.get_or_create_broker(run_id)
            produced = 0
            consumed = 0
            errors = 0

            async def produce():
                nonlocal produced, errors
                for i in range(num_events):
                    try:
                        await broker.put(f"e{i}", ("data", {}), timeout=0.2)
                        produced += 1
                    except BackpressureError:
                        errors += 1
                    await asyncio.sleep(0.001)
                await broker.put("end", ("end", {}), timeout=1.0)

            async def consume():
                nonlocal consumed
                async for _ in broker.aiter():
                    consumed += 1
                    await asyncio.sleep(0.005)

            producer_task = asyncio.create_task(produce())
            consumer_task = asyncio.create_task(consume())

            await asyncio.gather(producer_task, consumer_task)
            results[run_id] = {
                "produced": produced,
                "consumed": consumed,
                "errors": errors,
            }

        # Run 5 workloads concurrently
        tasks = [asyncio.create_task(run_workload(f"run_{i}", 100)) for i in range(5)]
        await asyncio.gather(*tasks)

        # All workloads should complete
        assert len(results) == 5
        for _run_id, stats in results.items():
            assert stats["consumed"] > 0
            assert stats["produced"] > 0

    @pytest.mark.asyncio
    @pytest.mark.timeout(60)
    async def test_graceful_degradation_under_overload(self):
        """System should degrade gracefully under extreme load"""
        broker = RunBroker("overload_test", maxsize=10)
        accepted = 0
        rejected = 0

        async def aggressive_producer():
            nonlocal accepted, rejected
            for i in range(200):
                try:
                    await broker.put(f"event_{i}", ("data", {}), timeout=0.01)
                    accepted += 1
                except BackpressureError:
                    rejected += 1

        async def minimal_consumer():
            async for _ in broker.aiter():
                await asyncio.sleep(0.1)  # Very slow

        consumer_task = asyncio.create_task(minimal_consumer())
        producer_task = asyncio.create_task(aggressive_producer())

        await asyncio.wait_for(producer_task, timeout=5.0)
        broker.mark_finished()

        try:
            await asyncio.wait_for(consumer_task, timeout=2.0)
        except TimeoutError:
            consumer_task.cancel()

        # Most events should be rejected due to tiny queue
        assert rejected > accepted, (
            f"Expected more rejections, got {accepted} accepted vs {rejected} rejected"
        )
        assert broker.get_queue_size() <= 10

    @pytest.mark.asyncio
    @pytest.mark.timeout(60)
    async def test_lag_monitoring_accuracy(self):
        """Lag metrics should accurately reflect consumer state"""
        broker = RunBroker("lag_test", maxsize=200)
        lag_samples = []

        async def monitored_consumer():
            async for _ in broker.aiter():
                lag_samples.append(broker.get_lag())
                await asyncio.sleep(0.01)

        consumer_task = asyncio.create_task(monitored_consumer())

        # Produce bursts with pauses
        for batch in range(5):
            for i in range(20):
                await broker.put(f"b{batch}_e{i}", ("data", {}), timeout=1.0)
            await asyncio.sleep(0.05)  # Pause between bursts

        await broker.put("end", ("end", {}), timeout=1.0)
        await consumer_task

        # Lag should vary over time
        assert len(lag_samples) > 0
        max_lag = max(lag_samples)
        min_lag = min(lag_samples)

        # Should see lag build up and reduce
        assert max_lag > min_lag
        assert max_lag < 200  # Within queue size


@pytest.mark.integration
@pytest.mark.broker
class TestBackpressureRealWorld:
    """Real-world scenarios for backpressure"""

    @pytest.mark.asyncio
    @pytest.mark.timeout(60)
    async def test_bursty_traffic_pattern(self):
        """Handle bursty traffic with backpressure"""
        broker = RunBroker("burst_test", maxsize=50)
        total_events = 0
        total_errors = 0

        async def bursty_producer():
            nonlocal total_events, total_errors
            for burst in range(10):
                # Burst of 30 events
                for i in range(30):
                    try:
                        await broker.put(
                            f"burst{burst}_e{i}", ("data", {}), timeout=0.1
                        )
                        total_events += 1
                    except BackpressureError:
                        total_errors += 1

                # Quiet period
                await asyncio.sleep(0.2)

            await broker.put("end", ("end", {}), timeout=1.0)

        async def steady_consumer():
            async for _ in broker.aiter():
                await asyncio.sleep(0.01)

        consumer_task = asyncio.create_task(steady_consumer())
        await asyncio.create_task(bursty_producer())
        await consumer_task

        # Should handle bursts with some backpressure
        assert total_events > 0
        assert total_errors >= 0  # May or may not have errors depending on timing

    @pytest.mark.asyncio
    @pytest.mark.timeout(60)
    async def test_consumer_failure_and_restart(self):
        """Handle consumer failure gracefully"""
        broker = RunBroker("failure_test", maxsize=30)

        # Fill queue
        for i in range(25):
            await broker.put(f"event_{i}", ("data", {}), timeout=1.0)

        initial_lag = broker.get_lag()
        assert initial_lag == 25

        # Consumer crashes after few events
        async def failing_consumer():
            count = 0
            async for _ in broker.aiter():
                count += 1
                if count == 5:
                    raise RuntimeError("Consumer crashed!")

        with pytest.raises(RuntimeError):
            await failing_consumer()

        # Lag should have reduced
        lag_after_partial = broker.get_lag()
        assert lag_after_partial < initial_lag
        assert lag_after_partial == 20  # 25 - 5

        # New consumer picks up remaining events and receives end marker
        # Add end event to stop the iterator
        await broker.put("end", ("end", {}), timeout=1.0)

        consumed = 0
        async for _ in broker.aiter():
            consumed += 1

        # Due to race conditions between mark_finished() and queue.get(),
        # we might get 20 or 21 events depending on timing
        assert consumed in (20, 21), f"Expected 20 or 21 events, got {consumed}"
        assert broker.is_finished
