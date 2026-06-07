"""
Module: test_parallel_migration_cursor_safety.py
Purpose: TDD tests for item 1.9 — verify that N parallel workers each get their own
         SqlServerConnector instance rather than sharing one.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from domains.migration.migration_engine import (
    DataExtractor,
    DataLoader,
    MigrationStrategy,
    TableMigrationPlan,
)
from domains.migration.parallel_migration import ParallelMigration, PartitionRange


class TestParallelMigrationConnectorPerWorker:
    """Item 1.9: each parallel worker must use its own connector, not share one."""

    @pytest.fixture
    def plan(self) -> TableMigrationPlan:
        return TableMigrationPlan(
            table_name="orders",
            schema_name="dbo",
            columns=["id", "amount"],
            row_count_estimate=300,
            strategy=MigrationStrategy.PARALLEL_CHUNKED,
            chunk_size=100,
        )

    def _make_extractor(self):
        ext = MagicMock(spec=DataExtractor)
        ext.extract_range = AsyncMock(return_value=[])
        ext.extract_range_with_hint = AsyncMock(return_value=[])
        connector = AsyncMock()
        connector.execute = AsyncMock(return_value=[{"cnt": 0}])
        ext._connector = connector
        return ext

    def _make_loader(self):
        loader = MagicMock(spec=DataLoader)
        loader.load_chunk = AsyncMock(return_value=0)
        return loader

    @pytest.mark.asyncio
    async def test_connector_factory_called_once_per_worker(self, plan):
        """A connector factory callable must be invoked once per worker, not shared."""
        num_workers = 4

        # Build a list of fresh connectors the factory will return
        fake_connectors = []
        for _ in range(num_workers):
            c = AsyncMock()
            c.connect = AsyncMock()
            c.disconnect = AsyncMock()
            c.execute = AsyncMock(return_value=[])
            fake_connectors.append(c)

        factory_calls = []

        def connector_factory():
            conn = fake_connectors[len(factory_calls)]
            factory_calls.append(conn)
            return conn

        extractor = self._make_extractor()
        loader = self._make_loader()

        migration = ParallelMigration(
            extractor=extractor,
            loader=loader,
            max_workers=num_workers,
            connector_factory=connector_factory,
        )

        # Supply explicit partition ranges so we can control the worker count
        ranges = [
            PartitionRange(partition_id=i, start_value=i * 100, end_value=(i + 1) * 100)
            for i in range(num_workers)
        ]

        await migration.migrate_with_ranges(plan, ranges, num_workers=num_workers)

        # Each worker must have obtained its own connector
        assert len(factory_calls) == num_workers, (
            f"Expected factory to be called {num_workers} times (once per worker), "
            f"got {len(factory_calls)}"
        )

    @pytest.mark.asyncio
    async def test_connector_factory_called_zero_times_when_no_ranges(self, plan):
        """If there are no partition ranges, the factory is never called."""
        factory_calls = []

        def connector_factory():
            factory_calls.append(True)
            c = AsyncMock()
            c.connect = AsyncMock()
            c.disconnect = AsyncMock()
            c.execute = AsyncMock(return_value=[])
            return c

        extractor = self._make_extractor()
        loader = self._make_loader()

        migration = ParallelMigration(
            extractor=extractor,
            loader=loader,
            max_workers=4,
            connector_factory=connector_factory,
        )

        await migration.migrate_with_ranges(plan, [], num_workers=4)
        assert factory_calls == []

    @pytest.mark.asyncio
    async def test_each_connector_receives_connect_call(self, plan):
        """Each connector obtained from the factory must have connect() called."""
        num_workers = 3
        connectors_connected = []

        def connector_factory():
            c = AsyncMock()

            async def _connect():
                connectors_connected.append(c)

            c.connect = _connect
            c.disconnect = AsyncMock()
            c.execute = AsyncMock(return_value=[])
            return c

        extractor = self._make_extractor()
        loader = self._make_loader()

        migration = ParallelMigration(
            extractor=extractor,
            loader=loader,
            max_workers=num_workers,
            connector_factory=connector_factory,
        )

        ranges = [
            PartitionRange(partition_id=i, start_value=i * 100, end_value=(i + 1) * 100)
            for i in range(num_workers)
        ]

        await migration.migrate_with_ranges(plan, ranges, num_workers=num_workers)

        assert len(connectors_connected) == num_workers, (
            "connect() must be called on every per-worker connector"
        )
        # All connectors must be distinct objects
        assert len(set(id(c) for c in connectors_connected)) == num_workers

    @pytest.mark.asyncio
    async def test_connectors_are_disconnected_after_worker_completes(self, plan):
        """Each per-worker connector must be disconnected after the worker finishes."""
        num_workers = 2
        disconnected = []

        def connector_factory():
            c = AsyncMock()
            c.connect = AsyncMock()

            async def _disconnect():
                disconnected.append(c)

            c.disconnect = _disconnect
            c.execute = AsyncMock(return_value=[])
            return c

        extractor = self._make_extractor()
        loader = self._make_loader()

        migration = ParallelMigration(
            extractor=extractor,
            loader=loader,
            max_workers=num_workers,
            connector_factory=connector_factory,
        )

        ranges = [
            PartitionRange(partition_id=i, start_value=i * 100, end_value=(i + 1) * 100)
            for i in range(num_workers)
        ]

        await migration.migrate_with_ranges(plan, ranges, num_workers=num_workers)
        assert len(disconnected) == num_workers

    @pytest.mark.asyncio
    async def test_migration_without_factory_still_works(self, plan):
        """When no factory is provided, ParallelMigration falls back to legacy mode."""
        extractor = self._make_extractor()
        loader = self._make_loader()

        # No connector_factory provided — should not raise
        migration = ParallelMigration(
            extractor=extractor,
            loader=loader,
            max_workers=2,
        )

        ranges = [PartitionRange(partition_id=0, start_value=0, end_value=100)]
        # Should complete without error (empty extractor returns no rows)
        await migration.migrate_with_ranges(plan, ranges, num_workers=1)
