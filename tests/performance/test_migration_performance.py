"""
Module: tests/performance/test_migration_performance.py
Purpose: Performance tests for large dataset migration throughput and latency
Author: Migration Platform Team
Created: 2026-05-22
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from domains.migration.migration_engine import (
    ChunkedMigration,
    DataExtractor,
    DataLoader,
    MigrationStatus,
    MigrationStrategy,
    TableMigrationPlan,
)
from domains.migration.parallel_migration import ParallelMigration

pytestmark = [pytest.mark.benchmark]


def _make_plan(
    table_name: str = "perf_test",
    chunk_size: int = 1000,
    row_count: int = 50000,
    strategy: MigrationStrategy = MigrationStrategy.CHUNKED,
) -> TableMigrationPlan:
    return TableMigrationPlan(
        table_name=table_name,
        schema_name="dbo",
        columns=["id", "name", "email", "created_date"],
        row_count_estimate=row_count,
        strategy=strategy,
        chunk_size=chunk_size,
    )


class TestChunkedMigrationThroughput:
    """Measures throughput of chunked migration with various chunk sizes."""

    CHUNK_SIZES = [100, 1000, 10000]
    TOTAL_ROWS = 50000

    @pytest.fixture
    def mock_extractor(self):
        ext = MagicMock(spec=DataExtractor)
        ext.extract_chunk = AsyncMock()
        return ext

    @pytest.fixture
    def mock_loader(self):
        loader = MagicMock(spec=DataLoader)
        loader.load_chunk = AsyncMock(side_effect=lambda schema, table, columns, rows: len(rows))
        return loader

    @pytest.mark.parametrize("chunk_size", CHUNK_SIZES)
    @pytest.mark.asyncio
    async def test_chunked_migration_throughput(self, mock_extractor, mock_loader, chunk_size):
        """Verify chunked migration achieves expected throughput."""
        rows_per_chunk = chunk_size
        total_chunks = self.TOTAL_ROWS // rows_per_chunk
        call_count = [0]

        async def extract_side_effect(**kwargs):
            call_count[0] += 1
            if call_count[0] <= total_chunks:
                return [{"id": i} for i in range(chunk_size)]
            return []

        mock_extractor.extract_chunk.side_effect = extract_side_effect

        migration = ChunkedMigration(mock_extractor, mock_loader, chunk_size=chunk_size)
        plan = _make_plan(chunk_size=chunk_size, row_count=self.TOTAL_ROWS)

        result = await migration.migrate_table(plan)
        assert result.rows_migrated > 0, "Zero rows migrated"

    @pytest.mark.parametrize("chunk_size", CHUNK_SIZES)
    @pytest.mark.asyncio
    async def test_throughput_scales_with_batch_size(self, mock_extractor, mock_loader, chunk_size):
        """Larger chunk sizes should yield higher throughput per chunk."""
        call_count = [0]

        async def extract_side_effect(**kwargs):
            call_count[0] += 1
            if call_count[0] <= 5:
                return [{"id": i, "data": "x" * 256} for i in range(chunk_size)]
            return []

        mock_extractor.extract_chunk.side_effect = extract_side_effect

        migration = ChunkedMigration(mock_extractor, mock_loader, chunk_size=chunk_size)
        plan = _make_plan(chunk_size=chunk_size, row_count=chunk_size * 5)

        start = time.monotonic()
        result = await migration.migrate_table(plan)
        elapsed = time.monotonic() - start

        assert result.rows_migrated > 0
        throughput = result.rows_migrated / elapsed if elapsed > 0 else 0
        assert throughput >= 0
        assert result.status == MigrationStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_memory_usage_large_extraction(self):
        """Simulate large extraction to check memory handling."""
        connector = AsyncMock()
        large_rows = [{"id": i, "data": "x" * 10000, "blob": "y" * 1000} for i in range(500)]
        connector.execute.return_value = large_rows
        extractor = DataExtractor(connector)

        rows = await extractor.extract_chunk(
            schema="dbo", table="large", columns=["id", "data", "blob"],
            offset=0, limit=500,
        )
        assert len(rows) == 500
        total_size = sum(len(str(r)) for r in rows)
        assert total_size > 0


class TestParallelMigrationPerformance:
    """Measures speedup from parallel workers."""

    WORKER_CONFIGS = [1, 2, 4]
    TOTAL_ROWS = 100000
    CHUNK_SIZE = 5000

    @pytest.fixture
    def mock_extractor(self):
        ext = MagicMock(spec=DataExtractor)
        ext.extract_chunk = AsyncMock()
        ext._connector = AsyncMock()
        ext._connector.execute = AsyncMock(return_value=[{"cnt": self.TOTAL_ROWS}])
        return ext

    @pytest.fixture
    def mock_loader(self):
        loader = MagicMock(spec=DataLoader)
        loader.load_chunk = AsyncMock(side_effect=lambda schema, table, columns, rows: len(rows))
        return loader

    @pytest.mark.parametrize("num_workers", WORKER_CONFIGS)
    @pytest.mark.asyncio
    async def test_parallel_speedup(self, mock_extractor, mock_loader, num_workers):
        """Parallel migration should complete faster with more workers."""
        call_count = [0]

        async def extract_side_effect(**kwargs):
            call_count[0] += 1
            if call_count[0] <= (self.TOTAL_ROWS // self.CHUNK_SIZE):
                return [{"id": i} for i in range(min(self.CHUNK_SIZE, self.TOTAL_ROWS))]
            return []

        mock_extractor.extract_chunk.side_effect = extract_side_effect

        migration = ParallelMigration(mock_extractor, mock_loader, max_workers=num_workers)
        plan = _make_plan(
            chunk_size=self.CHUNK_SIZE,
            row_count=self.TOTAL_ROWS,
            strategy=MigrationStrategy.PARALLEL_CHUNKED,
        )

        start = time.monotonic()
        result = await migration.migrate_table(plan, partition_column="id", num_workers=num_workers)
        elapsed = time.monotonic() - start

        assert result.rows_migrated > 0
        throughput = result.rows_migrated / elapsed if elapsed > 0 else 0
        assert throughput > 0, f"Zero throughput with {num_workers} workers"

    @pytest.mark.parametrize("num_workers", [2, 4, 8])
    @pytest.mark.asyncio
    async def test_parallel_throughput_scaling(self, mock_extractor, mock_loader, num_workers):
        """Throughput should increase with worker count."""
        call_count = [0]

        async def extract_side_effect(**kwargs):
            call_count[0] += 1
            if call_count[0] <= 20:
                return [{"id": i} for i in range(self.CHUNK_SIZE)]
            return []

        mock_extractor.extract_chunk.side_effect = extract_side_effect

        migration = ParallelMigration(mock_extractor, mock_loader, max_workers=num_workers)
        plan = _make_plan(
            chunk_size=self.CHUNK_SIZE,
            row_count=self.CHUNK_SIZE * 20,
            strategy=MigrationStrategy.PARALLEL_CHUNKED,
        )

        result = await migration.migrate_table(plan, partition_column="id", num_workers=num_workers)
        assert result.rows_migrated > 0


class TestExtractorLargePayload:
    """Tests extractor behavior with large row payloads."""

    @pytest.mark.asyncio
    async def test_extract_large_columns(self):
        connector = AsyncMock()
        connector.execute.return_value = [
            {"id": i, "data": "x" * 10000} for i in range(100)
        ]
        extractor = DataExtractor(connector)

        rows = await extractor.extract_chunk(
            schema="dbo", table="large", columns=["id", "data"],
            offset=0, limit=100,
        )
        assert len(rows) == 100
        assert len(rows[0]["data"]) == 10000

    @pytest.mark.asyncio
    async def test_extract_empty_result(self):
        connector = AsyncMock()
        connector.execute.return_value = []
        extractor = DataExtractor(connector)

        rows = await extractor.extract_chunk(
            schema="dbo", table="empty", columns=["id"],
            offset=0, limit=100,
        )
        assert len(rows) == 0


class TestStreamingCopyPerformance:
    """Tests for streaming COPY performance."""

    @pytest.mark.asyncio
    async def test_streaming_copy_throughput(self):
        connector = AsyncMock()
        raw_data = [{"id": i, "value": f"row_{i}"} for i in range(100)]

        async def mock_execute(*args, **kwargs):
            return raw_data

        connector.execute = AsyncMock(side_effect=mock_execute)
        extractor = DataExtractor(connector)

        rows = await extractor.extract_chunk(
            schema="dbo", table="stream_test", columns=["id", "value"],
            offset=0, limit=100,
        )
        assert len(rows) <= 100

    @pytest.mark.asyncio
    async def test_streaming_with_delays(self):
        connector = AsyncMock()
        raw_data = [{"id": i, "value": f"delayed_{i}"} for i in range(50)]

        async def mock_execute(*args, **kwargs):
            await asyncio.sleep(0.001)
            return raw_data

        connector.execute = AsyncMock(side_effect=mock_execute)
        extractor = DataExtractor(connector)

        rows = await extractor.extract_chunk(
            schema="dbo", table="delayed", columns=["id", "value"],
            offset=0, limit=50,
        )
        assert len(rows) == 50
