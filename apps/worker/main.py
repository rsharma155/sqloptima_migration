"""
Module: apps/worker/main.py
Purpose: Temporal.io worker service entry point
Author: Migration Platform Team
Created: 2026-05-22
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

import asyncio
import os
import signal
import sys

from infrastructure.temporal.client import TemporalWorkerService
from shared.logging.structured_logging import configure_logging, get_logger

logger = get_logger(__name__)


class WorkerApp:
    """Main worker application with graceful shutdown support."""

    def __init__(self) -> None:
        self._worker = TemporalWorkerService(
            host=os.environ.get("TEMPORAL_HOST", "localhost"),
            port=int(os.environ.get("TEMPORAL_PORT", "7233")),
            namespace=os.environ.get("TEMPORAL_NAMESPACE", "default"),
            task_queue=os.environ.get("TEMPORAL_TASK_QUEUE", "migration-platform"),
        )
        self._shutdown_event = asyncio.Event()

    def _setup_signal_handlers(self) -> None:
        if sys.platform != "win32":
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, self._shutdown_event.set)

    async def run(self) -> None:
        """Start the worker and wait for shutdown signal."""
        self._setup_signal_handlers()
        logger.info(
            "Starting Temporal worker",
            task_queue=self._worker._task_queue,
        )

        worker_task = asyncio.create_task(self._worker.start())
        await self._shutdown_event.wait()

        logger.info("Shutdown signal received, stopping worker...")
        await self._worker.stop()
        worker_task.cancel()
        logger.info("Worker stopped")


def main() -> None:
    configure_logging(level=os.environ.get("MIGRATION_LOG_LEVEL", "INFO"))
    asyncio.run(WorkerApp().run())


if __name__ == "__main__":
    main()
