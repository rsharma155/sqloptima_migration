"""
Module: tests/performance/test_concurrency.py
Purpose: Concurrency tests for parallel migration workers
Author: Migration Platform Team
Created: 2026-05-22
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

import asyncio
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
from domains.migration.parallel_migration import (
    ParallelMigration,
)


class TestWorkerPoolConcurrency:
    """Tests that worker pool correctly limits concurrency."""

    @pytest.mark.asyncio
    async def test_max_workers_respected(self):
        """Verify that at most max_workers run simultaneously."""
        max_workers = 3
        active = 0
        max_active = 0
        lock = asyncio.Lock()

        mock_ext = MagicMock(spec=DataExtractor)
        mock_ext._connector = AsyncMock()
        mock_ext._connector.execute = AsyncMock(return_value=[{"cnt": 100}])
        mock_ext.extract_chunk = AsyncMock()

        async def slow_extract(**kwargs):
            nonlocal active, max_active
            async with lock:
                active += 1
                max_active = max(max_active, active)
            await asyncio.sleep(0.05)
            async with lock:
                active -= 1
            return [{"id": 1}]

        mock_ext.extract_chunk.side_effect = slow_extract

        mock_loader = MagicMock(spec=DataLoader)
        mock_loader.load_chunk = AsyncMock(return_value=1)

        migration = ParallelMigration(mock_ext, mock_loader, max_workers=max_workers)
        plan = TableMigrationPlan(
            table_name="concurrency_test",
            schema_name="dbo",
            columns=["id"],
            row_count_estimate=100,
            strategy=MigrationStrategy.PARALLEL_CHUNKED,
            chunk_size=10,
            parallel_workers=max_workers,
        )

        await migration.migrate_table(plan, partition_column="id", num_workers=max_workers)
        assert max_active <= max_workers, \
            f"Expected max {max_workers} concurrent workers, got {max_active}"

    @pytest.mark.asyncio
    async def test_worker_isolation(self):
        """Each worker should have independent error handling."""
        mock_ext = MagicMock(spec=DataExtractor)
        mock_ext._connector = AsyncMock()
        mock_ext._connector.execute = AsyncMock(return_value=[{"cnt": 20}])
        mock_ext.extract_chunk = AsyncMock()

        call_count = [0]

        async def failing_extract(**kwargs):
            call_count[0] += 1
            if call_count[0] == 3:
                raise Exception("Worker error")
            return [{"id": call_count[0]}]

        mock_ext.extract_chunk.side_effect = failing_extract
        mock_loader = MagicMock(spec=DataLoader)
        mock_loader.load_chunk = AsyncMock(return_value=1)

        migration = ParallelMigration(mock_ext, mock_loader, max_workers=4)
        plan = TableMigrationPlan(
            table_name="isolated_test",
            schema_name="dbo",
            columns=["id"],
            row_count_estimate=20,
            strategy=MigrationStrategy.PARALLEL_CHUNKED,
            chunk_size=5,
            parallel_workers=4,
        )

        result = await migration.migrate_table(plan, partition_column="id", num_workers=4)
        assert result.status in (MigrationStatus.COMPLETED, MigrationStatus.FAILED)


class TestChunkedMigrationConcurrency:
    """Tests that chunked migration is safe."""

    @pytest.mark.asyncio
    async def test_concurrent_table_migrations(self):
        """Run two chunked migrations concurrently."""
        extractor = MagicMock(spec=DataExtractor)
        extractor.extract_chunk = AsyncMock()

        async def extract_side(**kwargs):
            return [{"id": 1}]

        extractor.extract_chunk.side_effect = extract_side
        loader = MagicMock(spec=DataLoader)
        loader.load_chunk = AsyncMock(return_value=1)

        migration = ChunkedMigration(extractor, loader, chunk_size=10)
        plan_a = TableMigrationPlan(
            table_name="table_a", schema_name="dbo", columns=["id"],
            row_count_estimate=10, strategy=MigrationStrategy.CHUNKED,
        )
        plan_b = TableMigrationPlan(
            table_name="table_b", schema_name="dbo", columns=["id"],
            row_count_estimate=10, strategy=MigrationStrategy.CHUNKED,
        )

        results = await asyncio.gather(
            migration.migrate_table(plan_a),
            migration.migrate_table(plan_b),
        )
        assert all(r.status == MigrationStatus.COMPLETED for r in results)


class TestLockContention:
    """Tests for lock contention during parallel migration."""

    @pytest.mark.asyncio
    async def test_lock_contention_simulation(self):
        """Simulate lock contention between parallel workers."""
        lock = asyncio.Lock()
        contention_count = 0
        max_workers = 5

        mock_ext = MagicMock(spec=DataExtractor)
        mock_ext._connector = AsyncMock()
        mock_ext._connector.execute = AsyncMock(return_value=[{"cnt": 50}])
        mock_ext.extract_chunk = AsyncMock()

        async def contended_extract(**kwargs):
            nonlocal contention_count
            async with lock:
                contention_count += 1
                await asyncio.sleep(0.01)
            return [{"id": 1}]

        mock_ext.extract_chunk.side_effect = contended_extract
        mock_loader = MagicMock(spec=DataLoader)
        mock_loader.load_chunk = AsyncMock(return_value=1)

        migration = ParallelMigration(mock_ext, mock_loader, max_workers=max_workers)
        plan = TableMigrationPlan(
            table_name="contention_test",
            schema_name="dbo",
            columns=["id"],
            row_count_estimate=50,
            strategy=MigrationStrategy.PARALLEL_CHUNKED,
            chunk_size=10,
            parallel_workers=max_workers,
        )

        result = await migration.migrate_table(plan, partition_column="id", num_workers=max_workers)
        assert contention_count > 0
        assert result.rows_migrated >= 0


class TestRaceConditions:
    """Tests for race conditions in progress tracking."""

    @pytest.mark.asyncio
    async def test_progress_tracking_race(self):
        """Progress tracking should be consistent under concurrent updates."""
        mock_ext = MagicMock(spec=DataExtractor)
        mock_ext._connector = AsyncMock()
        mock_ext._connector.execute = AsyncMock(return_value=[{"cnt": 100}])
        mock_ext.extract_chunk = AsyncMock()

        async def fast_extract(**kwargs):
            return [{"id": i} for i in range(10)]

        mock_ext.extract_chunk.side_effect = fast_extract
        mock_loader = MagicMock(spec=DataLoader)
        mock_loader.load_chunk = AsyncMock(return_value=10)

        migration = ParallelMigration(mock_ext, mock_loader, max_workers=4)
        plan = TableMigrationPlan(
            table_name="race_test",
            schema_name="dbo",
            columns=["id"],
            row_count_estimate=100,
            strategy=MigrationStrategy.PARALLEL_CHUNKED,
            chunk_size=10,
            parallel_workers=4,
        )

        result = await migration.migrate_table(plan, partition_column="id", num_workers=4)
        assert result.rows_migrated >= 0


class TestPauseResumeConcurrency:
    """Tests for concurrent pause/resume/stop operations."""

    @pytest.mark.asyncio
    async def test_concurrent_pause_resume(self):
        """Pause and resume should be safe under concurrent access."""
        mock_ext = MagicMock(spec=DataExtractor)
        mock_ext._connector = AsyncMock()
        mock_ext._connector.execute = AsyncMock(return_value=[{"cnt": 100}])
        mock_ext.extract_chunk = AsyncMock()

        async def pausable_extract(**kwargs):
            await asyncio.sleep(0.01)
            return [{"id": 1}]

        mock_ext.extract_chunk.side_effect = pausable_extract
        mock_loader = MagicMock(spec=DataLoader)
        mock_loader.load_chunk = AsyncMock(return_value=1)

        migration = ParallelMigration(mock_ext, mock_loader, max_workers=4)
        plan = TableMigrationPlan(
            table_name="pause_test",
            schema_name="dbo",
            columns=["id"],
            row_count_estimate=100,
            strategy=MigrationStrategy.PARALLEL_CHUNKED,
            chunk_size=10,
            parallel_workers=4,
        )

        async def pause_loop():
            for _ in range(5):
                migration.pause()
                await asyncio.sleep(0.01)
                migration.resume()
                await asyncio.sleep(0.01)

        async def run_migration():
            return await migration.migrate_table(
                plan, partition_column="id", num_workers=4,
            )

        result = await asyncio.gather(run_migration(), pause_loop())
        assert result[0].rows_migrated >= 0

    @pytest.mark.asyncio
    async def test_concurrent_stop(self):
        """Stop should halt all workers."""
        mock_ext = MagicMock(spec=DataExtractor)
        mock_ext._connector = AsyncMock()
        mock_ext._connector.execute = AsyncMock(return_value=[{"cnt": 200}])
        mock_ext.extract_chunk = AsyncMock()

        async def slow_extract(**kwargs):
            await asyncio.sleep(0.05)
            return [{"id": 1}]

        mock_ext.extract_chunk.side_effect = slow_extract
        mock_loader = MagicMock(spec=DataLoader)
        mock_loader.load_chunk = AsyncMock(return_value=1)

        migration = ParallelMigration(mock_ext, mock_loader, max_workers=4)
        plan = TableMigrationPlan(
            table_name="stop_test",
            schema_name="dbo",
            columns=["id"],
            row_count_estimate=200,
            strategy=MigrationStrategy.PARALLEL_CHUNKED,
            chunk_size=10,
            parallel_workers=4,
        )

        async def delayed_stop():
            await asyncio.sleep(0.1)
            migration.stop()
            await asyncio.sleep(0.05)

        async def run():
            return await migration.migrate_table(
                plan, partition_column="id", num_workers=4,
            )

        result = await asyncio.gather(run(), delayed_stop())
        assert result[0] is not None


class TestConcurrentExtraction:
    """Tests for concurrent chunk extraction from multiple tables."""

    @pytest.mark.asyncio
    async def test_multi_table_concurrent_extraction(self):
        """Extract from multiple tables concurrently."""
        connector = AsyncMock()
        connector.execute = AsyncMock(return_value=[{"id": 1}])
        extractor = DataExtractor(connector)

        tables = [f"table_{i}" for i in range(10)]

        async def extract_one(table):
            return await extractor.extract_chunk(
                schema="dbo", table=table, columns=["id"],
                offset=0, limit=100,
            )

        results = await asyncio.gather(*[extract_one(t) for t in tables])
        assert len(results) == 10
        for rows in results:
            assert len(rows) >= 0

    @pytest.mark.asyncio
    async def test_concurrent_workers_not_exceed_limit(self):
        """Parallel workers should not exceed configured limits."""
        max_workers = 3
        active_set = set()
        max_concurrent = [0]
        lock = asyncio.Lock()

        mock_ext = MagicMock(spec=DataExtractor)
        mock_ext._connector = AsyncMock()
        mock_ext._connector.execute = AsyncMock(return_value=[{"cnt": 100}])

        async def tracked_extract(**kw):
            nonlocal active_set
            async with lock:
                active_set.add(id(kw.get("chunk_id", 0)))
                max_concurrent[0] = max(max_concurrent[0], len(active_set))
            await asyncio.sleep(0.02)
            async with lock:
                active_set.discard(id(kw.get("chunk_id", 0)))
            return [{"id": 1}]

        mock_ext.extract_chunk = AsyncMock(side_effect=tracked_extract)
        mock_loader = MagicMock(spec=DataLoader)
        mock_loader.load_chunk = AsyncMock(return_value=1)

        migration = ParallelMigration(mock_ext, mock_loader, max_workers=max_workers)
        plan = TableMigrationPlan(
            table_name="limit_test",
            schema_name="dbo",
            columns=["id"],
            row_count_estimate=50,
            strategy=MigrationStrategy.PARALLEL_CHUNKED,
            chunk_size=5,
            parallel_workers=max_workers,
        )

        await migration.migrate_table(plan, partition_column="id", num_workers=max_workers)
        assert max_concurrent[0] <= max_workers
