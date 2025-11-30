"""Graceful shutdown manager for background tasks"""

import asyncio
import signal
from typing import Any

import structlog

logger = structlog.getLogger(__name__)


class ShutdownManager:
    """Manages graceful shutdown of background tasks"""

    def __init__(self, shutdown_timeout: float = 30.0):
        """Initialize shutdown manager.

        Args:
            shutdown_timeout: Max seconds to wait for tasks to complete
        """
        self.shutdown_timeout = shutdown_timeout
        self._shutdown_event = asyncio.Event()
        self._tasks: dict[str, asyncio.Task] = {}
        self._signal_handlers_installed = False

    def register_task(self, task_id: str, task: asyncio.Task) -> None:
        """Register a background task for tracking.

        Args:
            task_id: Unique identifier for the task
            task: The asyncio Task instance
        """
        self._tasks[task_id] = task
        logger.debug(f"Registered task {task_id}", task_count=len(self._tasks))

    def unregister_task(self, task_id: str) -> None:
        """Unregister a completed task.

        Args:
            task_id: The task identifier to remove
        """
        if task_id in self._tasks:
            del self._tasks[task_id]
            logger.debug(f"Unregistered task {task_id}", task_count=len(self._tasks))

    def is_shutting_down(self) -> bool:
        """Check if shutdown has been initiated."""
        return self._shutdown_event.is_set()

    def install_signal_handlers(self) -> None:
        """Install SIGTERM and SIGINT handlers for graceful shutdown."""
        if self._signal_handlers_installed:
            return

        def signal_handler(signum: int, _frame: Any) -> None:
            """Handle shutdown signals."""
            signame = signal.Signals(signum).name
            logger.info(f"Received {signame}, initiating graceful shutdown...")
            self._shutdown_event.set()

        # Install handlers for SIGTERM and SIGINT
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
        self._signal_handlers_installed = True
        logger.info("Signal handlers installed for graceful shutdown")

    async def shutdown(self) -> None:
        """Perform graceful shutdown of all tracked tasks."""
        if not self._tasks:
            logger.info("No active tasks to shutdown")
            return

        task_count = len(self._tasks)
        logger.info(f"Initiating graceful shutdown of {task_count} tasks...")

        # Set shutdown flag
        self._shutdown_event.set()

        # Cancel all tasks
        for task_id, task in self._tasks.items():
            if not task.done():
                logger.debug(f"Cancelling task {task_id}")
                task.cancel()

        # Wait for tasks to complete with timeout
        if self._tasks:
            try:
                # Gather all tasks and wait
                results = await asyncio.wait_for(
                    asyncio.gather(*self._tasks.values(), return_exceptions=True),
                    timeout=self.shutdown_timeout,
                )
                logger.info(f"Successfully shutdown {task_count} tasks")
            except asyncio.TimeoutError:
                logger.warning(
                    f"Shutdown timeout after {self.shutdown_timeout}s, "
                    f"some tasks may not have completed gracefully"
                )

        # Clear task registry
        self._tasks.clear()

    def get_active_task_count(self) -> int:
        """Get the number of currently tracked tasks."""
        return len(self._tasks)

    def get_active_task_ids(self) -> list[str]:
        """Get list of active task identifiers."""
        return list(self._tasks.keys())


# Global shutdown manager instance
shutdown_manager = ShutdownManager(shutdown_timeout=30.0)
