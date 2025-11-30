"""Event broker for managing run-specific event queues"""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any

import structlog

from .base_broker import BaseBrokerManager, BaseRunBroker

logger = structlog.getLogger(__name__)


class BackpressureError(Exception):
    """Raised when queue is full and backpressure is applied"""

    pass


class RunBroker(BaseRunBroker):
    """Manages event queuing and distribution for a specific run"""

    def __init__(self, run_id: str, maxsize: int = 10000):
        self.run_id = run_id
        self.queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue(maxsize=maxsize)
        self.finished = asyncio.Event()
        self._created_at = asyncio.get_event_loop().time()
        self._total_events = 0
        self._consumed_events = 0
        self._slow_consumer_threshold = 1000

    async def put(
        self, event_id: str, payload: Any, timeout: float | None = 5.0
    ) -> None:
        """Put an event into the broker queue with backpressure.

        Args:
            event_id: Unique event identifier
            payload: Event data
            timeout: Max seconds to wait if queue is full (None = wait forever)

        Raises:
            BackpressureError: If queue is full and timeout expires
        """
        if self.finished.is_set():
            logger.warning(
                f"Attempted to put event {event_id} into finished broker for run {self.run_id}"
            )
            return

        # Check consumer lag
        lag = self._total_events - self._consumed_events
        if lag > self._slow_consumer_threshold:
            logger.warning(
                f"Slow consumer detected for run {self.run_id}: {lag} events behind",
                run_id=self.run_id,
                lag=lag,
                threshold=self._slow_consumer_threshold,
            )

        # Put with timeout to detect backpressure
        try:
            if timeout is not None:
                await asyncio.wait_for(
                    self.queue.put((event_id, payload)), timeout=timeout
                )
            else:
                await self.queue.put((event_id, payload))

            self._total_events += 1

        except TimeoutError:
            logger.error(
                f"Queue full for run {self.run_id}, backpressure applied",
                run_id=self.run_id,
                queue_size=self.queue.qsize(),
                lag=lag,
            )
            raise BackpressureError(
                f"Queue full for run {self.run_id} after {timeout}s timeout"
            ) from None

        # Check if this is an end event
        if isinstance(payload, tuple) and len(payload) >= 1 and payload[0] == "end":
            self.mark_finished()

    async def aiter(self) -> AsyncIterator[tuple[str, Any]]:
        """Async iterator yielding (event_id, payload) pairs.

        Uses efficient event-based waiting instead of polling to reduce CPU usage.
        """
        while True:
            # Try non-blocking get first
            if not self.queue.empty():
                try:
                    event_id, payload = self.queue.get_nowait()
                    self._consumed_events += 1
                    yield event_id, payload

                    # Check if this is an end event
                    if (
                        isinstance(payload, tuple)
                        and len(payload) >= 1
                        and payload[0] == "end"
                    ):
                        break
                except asyncio.QueueEmpty:
                    pass

            # Check if finished and queue is empty
            if self.finished.is_set() and self.queue.empty():
                break

            # Wait for either new item or finish signal
            get_task = asyncio.create_task(self.queue.get())
            wait_task = asyncio.create_task(self.finished.wait())

            done, pending = await asyncio.wait(
                {get_task, wait_task}, return_when=asyncio.FIRST_COMPLETED
            )

            # Cancel pending tasks
            for task in pending:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

            # Process completed task
            for task in done:
                if task is get_task and not task.cancelled():
                    with contextlib.suppress(Exception):
                        event_id, payload = task.result()
                        self._consumed_events += 1
                        yield event_id, payload

                        # Check if this is an end event
                        if (
                            isinstance(payload, tuple)
                            and len(payload) >= 1
                            and payload[0] == "end"
                        ):
                            return
                elif task is wait_task:
                    # Finished signal received, drain queue and exit
                    while not self.queue.empty():
                        try:
                            event_id, payload = self.queue.get_nowait()
                            self._consumed_events += 1
                            yield event_id, payload
                        except asyncio.QueueEmpty:
                            break
                    return

    def mark_finished(self) -> None:
        """Mark this broker as finished"""
        self.finished.set()
        logger.debug(f"Broker for run {self.run_id} marked as finished")

    def is_finished(self) -> bool:
        """Check if this broker is finished"""
        return self.finished.is_set()

    def is_empty(self) -> bool:
        """Check if the queue is empty"""
        return self.queue.empty()

    def get_age(self) -> float:
        """Get the age of this broker in seconds"""
        return asyncio.get_event_loop().time() - self._created_at

    def get_lag(self) -> int:
        """Get the number of events behind consumers are"""
        return self._total_events - self._consumed_events

    def get_queue_size(self) -> int:
        """Get current queue size"""
        return self.queue.qsize()


class BrokerManager(BaseBrokerManager):
    """Manages multiple RunBroker instances"""

    def __init__(self, default_maxsize: int = 10000) -> None:
        self._brokers: dict[str, RunBroker] = {}
        self._cleanup_task: asyncio.Task | None = None
        self._default_maxsize = default_maxsize

    def get_or_create_broker(
        self, run_id: str, maxsize: int | None = None
    ) -> RunBroker:
        """Get or create a broker for a run

        Args:
            run_id: Run identifier
            maxsize: Max queue size (uses default if None)
        """
        if run_id not in self._brokers:
            size = maxsize if maxsize is not None else self._default_maxsize
            self._brokers[run_id] = RunBroker(run_id, maxsize=size)
            logger.debug(f"Created new broker for run {run_id} with maxsize={size}")
        return self._brokers[run_id]

    def get_broker(self, run_id: str) -> RunBroker | None:
        """Get an existing broker or None"""
        return self._brokers.get(run_id)

    def cleanup_broker(self, run_id: str) -> None:
        """Clean up a broker for a run"""
        if run_id in self._brokers:
            self._brokers[run_id].mark_finished()
            # Don't immediately delete in case there are still consumers
            logger.debug(f"Marked broker for run {run_id} for cleanup")

    def remove_broker(self, run_id: str) -> None:
        """Remove a broker completely"""
        if run_id in self._brokers:
            self._brokers[run_id].mark_finished()
            del self._brokers[run_id]
            logger.debug(f"Removed broker for run {run_id}")

    async def start_cleanup_task(self) -> None:
        """Start background cleanup task for old brokers"""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_old_brokers())

    async def stop_cleanup_task(self) -> None:
        """Stop background cleanup task"""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._cleanup_task

    async def _cleanup_old_brokers(self) -> None:
        """Background task to clean up old finished brokers"""
        while True:
            try:
                await asyncio.sleep(300)  # Check every 5 minutes

                asyncio.get_event_loop().time()
                to_remove = []

                for run_id, broker in self._brokers.items():
                    # Remove brokers that are finished and older than 1 hour
                    if (
                        broker.is_finished()
                        and broker.is_empty()
                        and broker.get_age() > 3600
                    ):
                        to_remove.append(run_id)

                for run_id in to_remove:
                    self.remove_broker(run_id)
                    logger.info(f"Cleaned up old broker for run {run_id}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in broker cleanup task: {e}")


# Global broker manager instance
broker_manager = BrokerManager()
