"""
Module: test_replication_message_bus.py
Purpose: TDD tests for in-memory replication message bus
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from apps.replicator.capture.models import ChangeEvent, ChangeOperation
from infrastructure.replication.message_bus import InMemoryChangeBus


class TestInMemoryChangeBus:
    async def test_publish_and_consume(self):
        bus = InMemoryChangeBus(maxsize=10)
        received: list[ChangeEvent] = []

        async def handler(event: ChangeEvent) -> None:
            received.append(event)

        await bus.start(handler)
        event = ChangeEvent(
            table_schema="public",
            table_name="orders",
            operation=ChangeOperation.INSERT,
            after_values={"id": 1},
        )
        await bus.publish(event)

        for _ in range(20):
            if received:
                break
            import asyncio
            await asyncio.sleep(0.05)

        await bus.stop()
        assert len(received) == 1
        assert received[0].table_name == "orders"
