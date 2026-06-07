"""
Module: tests/integration/replicator/test_replication_pipeline.py
Purpose: Integration test for the full poll → queue → apply pipeline
Author: Migration Platform Team
Created: 2026-05-22
Domain: Replication
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.replicator.apply.applier import ChangeApplier
from apps.replicator.apply.checkpoint import CheckpointStore
from apps.replicator.apply.deduplicator import Deduplicator
from apps.replicator.capture.agent import CaptureAgent
from apps.replicator.capture.models import (
    CaptureBatch,
    ChangeEvent,
    ChangeOperation,
    LsnPosition,
    TableInfo,
)
from apps.replicator.capture.providers.base import AbstractCaptureProvider
from apps.replicator.capture.publisher import MessagePublisher


class IntegrationWatermarkProvider(AbstractCaptureProvider):
    """Test provider that returns synthetic watermark-based changes."""

    def __init__(self) -> None:
        self._call_count = 0

    async def connect(self, connection_string: str) -> None:
        pass

    async def discover_tables(self, schema: str) -> list[TableInfo]:
        return [
            TableInfo(
                schema_name=schema,
                table_name="orders",
                columns=["id", "status", "updated_at"],
                pk_columns=["id"],
                watermark_column="updated_at",
            ),
        ]

    async def capture_changes(
        self,
        table: TableInfo,
        last_position: bytes | None = None,
        batch_size: int = 1000,
    ) -> CaptureBatch:
        self._call_count += 1
        if self._call_count > 3:
            zero_lsn = LsnPosition.from_string("0x00000000:00000000:0000")
            return CaptureBatch(changes=[], new_position=zero_lsn)

        changes = [
            ChangeEvent(
                table_schema=table.schema_name,
                table_name=table.table_name,
                operation=ChangeOperation.INSERT,
                after_values={
                    "id": self._call_count,
                    "status": "active",
                    "updated_at": f"2026-05-22T12:00:0{self._call_count}",
                },
            ),
        ]
        lsn = LsnPosition.from_string(f"0x00000000:00000000:000{self._call_count}")
        return CaptureBatch(changes=changes, new_position=lsn)

    async def take_snapshot(
        self,
        table: TableInfo,
        callback,
        chunk_size: int = 10000,
    ) -> None:
        pass


class TestReplicationPipeline:
    """End-to-end test: watermark capture → serialize → publish → apply."""

    @pytest.mark.asyncio
    async def test_full_pipeline(self):
        provider = IntegrationWatermarkProvider()
        publisher = MagicMock(spec=MessagePublisher)
        publisher.publish = AsyncMock(return_value=True)

        agent = CaptureAgent(provider=provider, publisher=publisher, poll_interval_ms=50000)

        tables = await agent.start(schema="dbo")
        assert len(tables) == 1

        tables = await provider.discover_tables("dbo")
        assert len(tables) == 1
        table = tables[0]

        # Run a few capture cycles
        for _ in range(3):
            count = await agent._capture_and_publish(table)
            assert count == 1

        assert publisher.publish.call_count == 3

        await agent.stop()

    @pytest.mark.asyncio
    async def test_pipeline_with_apply(self):
        provider = IntegrationWatermarkProvider()
        publisher = MagicMock(spec=MessagePublisher)
        publisher.publish = AsyncMock(return_value=True)

        conn = AsyncMock()
        conn.execute = AsyncMock()
        checkpoint = CheckpointStore(conn)
        dedup = Deduplicator(max_size=100)
        applier = ChangeApplier(conn, checkpoint, dedup)

        agent = CaptureAgent(provider=provider, publisher=publisher)

        tables = await agent.start(schema="dbo")
        table = tables[0]

        for _ in range(2):
            batch = await provider.capture_changes(table)
            for event in batch.changes:
                await agent._publisher.publish(event)
                await applier.apply(event, pk_columns=["id"])

        assert publisher.publish.call_count == 2
        assert conn.execute.call_count == 2

        await agent.stop()

    @pytest.mark.asyncio
    async def test_deduplication_across_pipeline(self):
        conn = AsyncMock()
        conn.execute = AsyncMock()
        checkpoint = CheckpointStore(conn)
        dedup = Deduplicator(max_size=100)
        applier = ChangeApplier(conn, checkpoint, dedup)

        lsn = LsnPosition.from_string("0x00001234:0000ABCD:0001")
        event = ChangeEvent(
            table_schema="dbo",
            table_name="users",
            operation=ChangeOperation.INSERT,
            after_values={"id": 1, "name": "Alice"},
            lsn=lsn,
        )

        # First apply should execute (UPSERT + checkpoint save = 2 calls)
        r1 = await applier.apply(event, pk_columns=["id"])
        assert r1 is True
        assert conn.execute.call_count == 2

        # Second apply with same LSN should skip (dedup hit)
        r2 = await applier.apply(event, pk_columns=["id"])
        assert r2 is True
        assert conn.execute.call_count == 2  # not called again

    @pytest.mark.asyncio
    async def test_capture_agent_discover_and_stop(self):
        provider = IntegrationWatermarkProvider()
        publisher = MagicMock(spec=MessagePublisher)
        publisher.publish = AsyncMock(return_value=True)

        agent = CaptureAgent(provider=provider, publisher=publisher)

        tables = await agent.discover_tables("dbo")
        assert len(tables) == 1
        assert tables[0].table_name == "orders"

        await agent.start(schema="dbo")
        assert agent._running is True

        await agent.stop()
        assert agent._running is False
