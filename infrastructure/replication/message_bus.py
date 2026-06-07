"""
Module: message_bus.py
Purpose: Lightweight in-process change bus (bounded memory) with optional RabbitMQ bridge
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from apps.replicator.capture.envelope import event_from_envelope, event_to_envelope
from apps.replicator.capture.models import ChangeEvent
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)

ConsumerHandler = Callable[[ChangeEvent], Awaitable[None]]


class InMemoryChangeBus:
    """Bounded asyncio queue for single-process replication (low memory footprint)."""

    def __init__(self, maxsize: int = 2000) -> None:
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=maxsize)
        self._consumer_task: asyncio.Task | None = None
        self._handler: ConsumerHandler | None = None
        self._running = False
        self.events_delivered = 0

    async def publish(self, event: ChangeEvent) -> bool:
        envelope = event_to_envelope(event)
        await self._queue.put(envelope)
        return True

    async def start(self, handler: ConsumerHandler) -> None:
        self._handler = handler
        self._running = True
        self._consumer_task = asyncio.create_task(self._consume_loop(), name="replication-bus")

    async def stop(self) -> None:
        self._running = False
        if self._consumer_task:
            self._consumer_task.cancel()
            await asyncio.gather(self._consumer_task, return_exceptions=True)
            self._consumer_task = None

    async def _consume_loop(self) -> None:
        while self._running:
            try:
                envelope = await asyncio.wait_for(self._queue.get(), timeout=0.5)
            except TimeoutError:
                continue
            if self._handler is None:
                continue
            try:
                event = event_from_envelope(envelope)
                await self._handler(event)
                self.events_delivered += 1
            except Exception:
                logger.exception("change_bus_handler_failed", envelope_id=envelope.get("id"))

    @property
    def depth(self) -> int:
        return self._queue.qsize()


class LoopbackPublisher:
    """Publisher adapter that writes directly to an InMemoryChangeBus."""

    def __init__(self, bus: InMemoryChangeBus) -> None:
        self._bus = bus

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def publish(self, event: ChangeEvent) -> bool:
        return await self._bus.publish(event)


class RabbitMqBridgeConsumer:
    """Consumes RabbitMQ messages and forwards to a handler (optional external broker)."""

    def __init__(
        self,
        url: str,
        handler: ConsumerHandler,
        *,
        target_schema: str | None = None,
        queue_name: str = "cdc.apply",
        prefetch: int = 10,
    ) -> None:
        self._url = url
        self._handler = handler
        self._target_schema = target_schema
        self._queue_name = queue_name
        self._prefetch = prefetch
        self._task: asyncio.Task | None = None
        self._running = False
        self.events_applied = 0

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run(), name="rabbitmq-consumer")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def _run(self) -> None:
        try:
            import aio_pika
        except ImportError:
            logger.warning("aio_pika_not_installed", detail="RabbitMQ consumer disabled")
            return

        connection = await aio_pika.connect_robust(self._url)
        try:
            channel = await connection.channel()
            await channel.set_qos(prefetch_count=self._prefetch)
            queue = await channel.declare_queue(self._queue_name, durable=True)
            async with queue.iterator() as queue_iter:
                async for message in queue_iter:
                    if not self._running:
                        break
                    async with message.process():
                        payload = json.loads(message.body.decode())
                        event = event_from_envelope(payload, target_schema=self._target_schema)
                        await self._handler(event)
                        self.events_applied += 1
        finally:
            await connection.close()
