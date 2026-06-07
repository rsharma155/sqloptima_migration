"""
Module: test_parallel_migration.py
Purpose: Unit tests
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

import pytest

from domains.migration.migration_engine import (
    DataExtractor,
    DataLoader,
    MigrationStatus,
    MigrationStrategy,
    TableMigrationPlan,
)
from domains.migration.parallel_migration import (
    ParallelMigration,
    PartitionRange,
    PartitionStrategy,
    WorkerResult,
)


class TestPartitionRange:
    def test_create_range(self):
        pr = PartitionRange(partition_id=0, start_value=0, end_value=100)
        assert pr.partition_id == 0
        assert pr.start_value == 0


class TestWorkerResult:
    def test_create(self):
        wr = WorkerResult(worker_id=1, partition_id=0, rows_migrated=100, chunks=[], success=True)
        assert wr.success is True
        assert wr.rows_migrated == 100


class TestPartitionStrategyIdentifierValidation:
    """Injection-prevention: identifier arguments must be validated before building SQL."""

    @pytest.mark.asyncio
    async def test_compute_ranges_rejects_bad_schema(self):
        mock_conn = AsyncMock()
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            await PartitionStrategy.compute_ranges(
                mock_conn, "dbo; DROP TABLE--", "users", "id", 4
            )

    @pytest.mark.asyncio
    async def test_compute_ranges_rejects_bad_table(self):
        mock_conn = AsyncMock()
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            await PartitionStrategy.compute_ranges(
                mock_conn, "dbo", "users; DELETE FROM users--", "id", 4
            )

    @pytest.mark.asyncio
    async def test_compute_ranges_rejects_bad_column(self):
        mock_conn = AsyncMock()
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            await PartitionStrategy.compute_ranges(
                mock_conn, "dbo", "users", "id; DROP TABLE--", 4
            )

    @pytest.mark.asyncio
    async def test_compute_ranges_rejects_non_int_partitions(self):
        mock_conn = AsyncMock()
        with pytest.raises(ValueError, match="num_partitions"):
            await PartitionStrategy.compute_ranges(
                mock_conn, "dbo", "users", "id", -1
            )

    @pytest.mark.asyncio
    async def test_compute_id_ranges_rejects_bad_schema(self):
        mock_conn = AsyncMock()
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            await PartitionStrategy.compute_id_ranges(
                mock_conn, "dbo'; DROP TABLE--", "users", "id", 1000
            )

    @pytest.mark.asyncio
    async def test_compute_id_ranges_rejects_bad_table(self):
        mock_conn = AsyncMock()
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            await PartitionStrategy.compute_id_ranges(
                mock_conn, "dbo", "users OR 1=1--", "id", 1000
            )


class TestPartitionStrategy:
    @pytest.mark.asyncio
    async def test_compute_id_ranges(self):
        mock_conn = AsyncMock()
        mock_conn.execute.return_value = [{"cnt": 5000}]

        ranges = await PartitionStrategy.compute_id_ranges(
            mock_conn, "dbo", "users", "id", chunk_size=1000
        )
        assert len(ranges) == 5
        assert ranges[0].start_value == 0
        assert ranges[4].start_value == 4000

    @pytest.mark.asyncio
    async def test_empty_table(self):
        mock_conn = AsyncMock()
        mock_conn.execute.return_value = [{"cnt": 0}]

        ranges = await PartitionStrategy.compute_id_ranges(
            mock_conn, "dbo", "empty", "id", chunk_size=1000
        )
        assert len(ranges) == 0

    @pytest.mark.asyncio
    async def test_compute_deterministic_ranges(self):
        mock_conn = AsyncMock()

        async def execute_side_effect(query, params=None):
            if "MIN" in query and "MAX" in query:
                return [{"min_val": 1, "max_val": 10000}]
            if "sys.partitions" in query:
                return [{"row_count": 10000}]
            if "is_primary_key" in query or "sys.indexes" in query:
                return [{"column_name": "id", "type_name": "bigint", "is_identity": True}]
            return []

        mock_conn.execute = execute_side_effect

        ranges = await PartitionStrategy.compute_deterministic_ranges(
            mock_conn, "dbo", "users", "id", chunk_size=1000, max_partitions=4
        )
        assert len(ranges) >= 1
        assert ranges[0].start_value is not None


class TestParallelMigration:
    @pytest.fixture
    def mock_extractor(self):
        ext = MagicMock(spec=DataExtractor)
        ext.extract_chunk = AsyncMock()
        ext.extract_range = AsyncMock()
        ext.extract_range_with_hint = AsyncMock()
        ext._connector = AsyncMock()

        async def conn_execute(query, params=None):
            if "MIN" in query and "MAX" in query:
                return [{"min_val": 1, "max_val": 10000}]
            if "sys.partitions" in query:
                return [{"row_count": 10000}]
            if "is_primary_key" in query or "sys.indexes" in query:
                return [{"column_name": "id", "type_name": "bigint", "is_identity": True}]
            if "COUNT(*)" in query:
                return [{"cnt": 100}]
            return []

        ext._connector.execute = conn_execute
        return ext

    @pytest.fixture
    def mock_loader(self):
        loader = MagicMock(spec=DataLoader)
        loader.load_chunk = AsyncMock(side_effect=lambda schema, table, columns, rows: len(rows))
        return loader

    @pytest.fixture
    def migration(self, mock_extractor, mock_loader):
        return ParallelMigration(mock_extractor, mock_loader, max_workers=2)

    @pytest.mark.asyncio
    async def test_migrate_single_partition(self, migration, mock_extractor, mock_loader):
        call_count = [0]

        async def extract_range_side_effect(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
            return []

        mock_extractor.extract_range.side_effect = extract_range_side_effect

        plan = TableMigrationPlan(
            table_name="users",
            schema_name="dbo",
            columns=["id", "name"],
            row_count_estimate=2,
            strategy=MigrationStrategy.PARALLEL_CHUNKED,
            chunk_size=100,
        )

        result = await migration.migrate_table(plan, partition_column="id", num_workers=1)
        assert result.rows_migrated == 2

    @pytest.mark.asyncio
    async def test_empty_table(self, migration, mock_extractor, mock_loader):
        mock_extractor._connector.execute.return_value = [{"cnt": 0}]
        mock_extractor.extract_range.return_value = []

        plan = TableMigrationPlan(
            table_name="empty",
            schema_name="dbo",
            columns=["id"],
            row_count_estimate=0,
            strategy=MigrationStrategy.PARALLEL_CHUNKED,
        )

        result = await migration.migrate_table(plan, partition_column="id")
        assert result.status in (MigrationStatus.COMPLETED,)

    @pytest.mark.asyncio
    async def test_handles_extract_error(self, migration, mock_extractor, mock_loader):
        async def conn_execute(query, params=None):
            if "MIN" in query and "MAX" in query:
                return [{"min_val": 1, "max_val": 100}]
            if "sys.partitions" in query:
                return [{"row_count": 100}]
            if "is_primary_key" in query or "sys.indexes" in query:
                return [{"column_name": "id", "type_name": "int", "is_identity": True}]
            if "COUNT(*)" in query:
                return [{"cnt": 100}]
            return []

        mock_extractor._connector.execute = conn_execute
        mock_extractor.extract_range.side_effect = Exception("DB error")

        plan = TableMigrationPlan(
            table_name="failing",
            schema_name="dbo",
            columns=["id"],
            row_count_estimate=100,
            strategy=MigrationStrategy.PARALLEL_CHUNKED,
            chunk_size=50,
        )

        with unittest.mock.patch(
            "domains.migration.parallel_migration.RETRY_DELAYS_SEC",
            [0, 0, 0],
        ):
            result = await migration.migrate_table(plan, partition_column="id", num_workers=1)
            assert result.status == MigrationStatus.FAILED
            assert result.error is not None
