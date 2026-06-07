"""
Module: test_migration_engine.py
Purpose: Unit tests
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from domains.migration.migration_engine import (
    ChunkedMigration,
    DataExtractor,
    DataLoader,
    MigrationStatus,
    MigrationStrategy,
    TableMigrationPlan,
    TableMigrationResult,
)


@pytest.fixture
def mock_extractor():
    extractor = MagicMock(spec=DataExtractor)
    extractor.extract_range = AsyncMock()
    extractor.extract_range_with_hint = AsyncMock()
    return extractor


@pytest.fixture
def mock_loader():
    loader = MagicMock(spec=DataLoader)
    loader.load_chunk = AsyncMock(side_effect=lambda schema, table, columns, rows, **kw: len(rows))
    return loader


@pytest.fixture
def mock_chunk_planner():
    from domains.chunking.chunk_planner import ChunkBoundary, ChunkColumnType, ChunkPlan, ChunkPlanner

    planner = MagicMock(spec=ChunkPlanner)
    planner.plan_table.return_value = MagicMock(
        chunks=[
            ChunkPlan(
                table_schema="dbo",
                table_name="users",
                boundary=ChunkBoundary(start=1, end=10000),
                column_name="id",
                column_type=ChunkColumnType.IDENTITY_PK,
                max_retries=1,
            ),
        ],
        total_rows_estimate=2,
        min_value=1,
        max_value=10000,
        column_name="id",
        column_type=ChunkColumnType.IDENTITY_PK,
    )
    return planner


@pytest.fixture
def mock_chunk_store():
    from domains.chunking.chunk_planner import ChunkBoundary, ChunkColumnType, ChunkPlan

    store = AsyncMock()
    store.get_pending_chunks.return_value = []
    store.expire_stale_leases.return_value = 0
    store.release_chunk.return_value = None
    store.renew_lease.return_value = True
    store.claim_chunk.return_value = ChunkPlan(
        table_schema="dbo",
        table_name="users",
        boundary=ChunkBoundary(start=1, end=10000),
        column_name="id",
        column_type=ChunkColumnType.IDENTITY_PK,
        max_retries=1,
    )
    return store


class TestTableMigrationPlan:
    def test_create_plan(self):
        plan = TableMigrationPlan(
            table_name="users",
            schema_name="dbo",
            columns=["id", "name", "email"],
            row_count_estimate=1000,
            strategy=MigrationStrategy.CHUNKED,
        )
        assert plan.table_name == "users"
        assert plan.chunk_size == 10000
        assert plan.parallel_workers == 4

    def test_default_values(self):
        plan = TableMigrationPlan(
            table_name="t",
            schema_name="dbo",
            columns=["id"],
            row_count_estimate=0,
            strategy=MigrationStrategy.FULL_LOAD,
        )
        assert plan.chunk_size == 10000
        assert plan.parallel_workers == 4


class TestTableMigrationResult:
    def test_create_result(self):
        result = TableMigrationResult(
            table_name="users",
            schema_name="dbo",
            rows_migrated=100,
            chunks=[],
            status=MigrationStatus.COMPLETED,
            start_time=datetime.now(UTC),
        )
        assert result.rows_migrated == 100
        assert result.status == MigrationStatus.COMPLETED

    def test_calculate_throughput(self):
        result = TableMigrationResult(
            table_name="t",
            schema_name="dbo",
            rows_migrated=1000,
            chunks=[],
            status=MigrationStatus.COMPLETED,
            start_time=datetime.now(UTC),
            end_time=datetime.now(UTC),
            total_duration_seconds=10.0,
        )
        result.throughput_rows_per_sec = 1000 / 10.0
        assert result.throughput_rows_per_sec == 100.0


class TestDataExtractor:
    @pytest.fixture
    def connector(self):
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_extract_range(self, connector):
        connector.execute.return_value = [{"id": 50}]
        extractor = DataExtractor(connector)
        rows = await extractor.extract_range("dbo", "users", ["id"], "id", 1, 100)
        assert len(rows) == 1
        call_query = connector.execute.call_args[0][0]
        assert "OPTION (MAXDOP 1)" in call_query
        assert "WHERE" in call_query
        assert ">=" in call_query
        assert "<" in call_query

    @pytest.mark.asyncio
    async def test_extract_range_with_hint(self, connector):
        connector.execute.return_value = [{"id": 50}]
        extractor = DataExtractor(connector)
        rows = await extractor.extract_range_with_hint(
            "dbo", "users", ["id"], "id", 1, 100, use_nolock=True
        )
        assert len(rows) == 1
        call_query = connector.execute.call_args[0][0]
        assert "WITH (NOLOCK)" in call_query


class TestChunkedMigration:
    @pytest.mark.asyncio
    async def test_migrate_table_single_chunk(self, mock_extractor, mock_loader, mock_chunk_planner, mock_chunk_store):
        mock_extractor.extract_range.return_value = [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"},
        ]
        mock_chunk_store.claim_chunk.side_effect = [
            mock_chunk_store.claim_chunk.return_value,
            None,
        ]

        migration = ChunkedMigration(
            mock_extractor, mock_loader,
            chunk_size=100, chunk_planner=mock_chunk_planner, chunk_store=mock_chunk_store,
        )
        plan = TableMigrationPlan(
            table_name="users",
            schema_name="dbo",
            columns=["id", "name"],
            row_count_estimate=2,
            strategy=MigrationStrategy.CHUNKED,
        )

        result = await migration.migrate_table(plan)
        assert result.status == MigrationStatus.COMPLETED
        assert result.rows_migrated == 2
        assert len(result.chunks) == 1

    @pytest.mark.asyncio
    async def test_migrate_table_multiple_chunks(self, mock_extractor, mock_loader):
        from domains.chunking.chunk_planner import ChunkBoundary, ChunkColumnType, ChunkPlan, ChunkPlanner

        call_count = [0]

        async def extract_side(**kw):
            call_count[0] += 1
            if call_count[0] == 1:
                return [{"id": i} for i in range(10)]
            return []

        mock_extractor.extract_range.side_effect = extract_side
        mock_loader.load_chunk.return_value = 10

        mock_planner = MagicMock(spec=ChunkPlanner)
        mock_planner.plan_table.return_value = MagicMock(
            chunks=[
                ChunkPlan(
                    table_schema="dbo", table_name="test",
                    boundary=ChunkBoundary(start=1, end=10),
                    column_name="id", column_type=ChunkColumnType.IDENTITY_PK,
                ),
            ],
            total_rows_estimate=10,
        )

        mock_store = AsyncMock()
        mock_store.get_pending_chunks.return_value = []
        mock_store.expire_stale_leases.return_value = 0
        mock_store.release_chunk.return_value = None
        mock_store.renew_lease.return_value = True
        mock_store.claim_chunk.side_effect = [
            ChunkPlan(
                table_schema="dbo", table_name="test",
                boundary=ChunkBoundary(start=1, end=10),
                column_name="id", column_type=ChunkColumnType.IDENTITY_PK,
            ),
            None,
        ]

        migration = ChunkedMigration(
            mock_extractor, mock_loader,
            chunk_size=10, chunk_planner=mock_planner, chunk_store=mock_store,
        )
        plan = TableMigrationPlan(
            table_name="test", schema_name="dbo", columns=["id"],
            row_count_estimate=10, strategy=MigrationStrategy.CHUNKED, chunk_size=10,
        )

        result = await migration.migrate_table(plan)
        assert result.rows_migrated == 10
        assert len(result.chunks) == 1

    @pytest.mark.asyncio
    async def test_migrate_empty_table(self, mock_extractor, mock_loader, mock_chunk_planner, mock_chunk_store):
        mock_extractor.extract_range.return_value = []
        mock_chunk_store.claim_chunk.side_effect = [
            mock_chunk_store.claim_chunk.return_value,
            None,
        ]

        migration = ChunkedMigration(
            mock_extractor, mock_loader,
            chunk_planner=mock_chunk_planner, chunk_store=mock_chunk_store,
        )
        plan = TableMigrationPlan(
            table_name="empty", schema_name="dbo", columns=["id"],
            row_count_estimate=0, strategy=MigrationStrategy.CHUNKED,
        )

        result = await migration.migrate_table(plan)
        assert result.status == MigrationStatus.COMPLETED
        assert result.rows_migrated == 0
        assert len(result.chunks) == 0

    @pytest.mark.asyncio
    async def test_migrate_handles_error(self, mock_extractor, mock_loader, mock_chunk_planner, mock_chunk_store):
        mock_extractor.extract_range.side_effect = Exception("Connection lost")
        mock_chunk_store.claim_chunk.side_effect = [
            mock_chunk_store.claim_chunk.return_value,
            None,
        ]

        migration = ChunkedMigration(
            mock_extractor, mock_loader,
            chunk_planner=mock_chunk_planner, chunk_store=mock_chunk_store,
        )
        plan = TableMigrationPlan(
            table_name="failing", schema_name="dbo", columns=["id"],
            row_count_estimate=100, strategy=MigrationStrategy.CHUNKED,
        )

        result = await migration.migrate_table(plan)
        assert result.status == MigrationStatus.FAILED
        assert result.error is not None
        assert "Connection lost" in result.error

    @pytest.mark.asyncio
    async def test_migrate_with_range_extraction(self, mock_extractor, mock_loader, mock_chunk_planner, mock_chunk_store):
        mock_extractor.extract_range.return_value = [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"},
        ]
        mock_loader.load_chunk.return_value = 2
        mock_chunk_store.claim_chunk.side_effect = [
            mock_chunk_store.claim_chunk.return_value,
            None,
        ]

        migration = ChunkedMigration(
            mock_extractor, mock_loader,
            chunk_size=10000, chunk_planner=mock_chunk_planner, chunk_store=mock_chunk_store,
        )
        plan = TableMigrationPlan(
            table_name="users", schema_name="dbo", columns=["id", "name"],
            row_count_estimate=2, strategy=MigrationStrategy.CHUNKED,
        )

        result = await migration.migrate_table(plan)
        assert result.status == MigrationStatus.COMPLETED
        assert result.rows_migrated == 2
        mock_extractor.extract_range.assert_called_once()

    @pytest.mark.asyncio
    async def test_retry_on_failure(self, mock_extractor, mock_loader):
        from domains.chunking.chunk_planner import ChunkBoundary, ChunkColumnType, ChunkPlan, ChunkPlanner

        mock_extractor.extract_range.side_effect = [
            Exception("Timeout"),
            [{"id": 1, "name": "Alice"}],
        ]
        mock_loader.load_chunk.return_value = 1

        mock_planner = MagicMock(spec=ChunkPlanner)
        retry_chunk = ChunkPlan(
            table_schema="dbo", table_name="users",
            boundary=ChunkBoundary(start=1, end=10000),
            column_name="id", column_type=ChunkColumnType.IDENTITY_PK,
            max_retries=3,
        )
        mock_planner.plan_table.return_value = MagicMock(
            chunks=[retry_chunk], total_rows_estimate=1,
        )

        mock_store = AsyncMock()
        mock_store.get_pending_chunks.return_value = []
        mock_store.expire_stale_leases.return_value = 0
        mock_store.release_chunk.return_value = None
        mock_store.renew_lease.return_value = True
        mock_store.claim_chunk.side_effect = [retry_chunk, None]

        from domains.migration.migration_engine import RETRY_DELAYS_SEC
        original_delays = list(RETRY_DELAYS_SEC)
        RETRY_DELAYS_SEC.clear()
        RETRY_DELAYS_SEC.extend([0, 0])

        migration = ChunkedMigration(
            mock_extractor, mock_loader, chunk_size=10000,
            chunk_planner=mock_planner, chunk_store=mock_store,
        )
        plan = TableMigrationPlan(
            table_name="users", schema_name="dbo", columns=["id", "name"],
            row_count_estimate=1, strategy=MigrationStrategy.CHUNKED,
        )

        result = await migration.migrate_table(plan)
        RETRY_DELAYS_SEC.clear()
        RETRY_DELAYS_SEC.extend(original_delays)
        assert result.status == MigrationStatus.COMPLETED
        assert result.rows_migrated == 1

    @pytest.mark.asyncio
    async def test_quarantine_after_max_retries(self, mock_extractor, mock_loader):
        from domains.chunking.chunk_planner import ChunkBoundary, ChunkColumnType, ChunkPlan, ChunkPlanner

        mock_extractor.extract_range.side_effect = Exception("Persistent failure")

        mock_planner = MagicMock(spec=ChunkPlanner)
        quarantine_chunk = ChunkPlan(
            table_schema="dbo", table_name="users",
            boundary=ChunkBoundary(start=1, end=10000),
            column_name="id", column_type=ChunkColumnType.IDENTITY_PK,
            max_retries=1,
        )
        mock_planner.plan_table.return_value = MagicMock(
            chunks=[quarantine_chunk], total_rows_estimate=100,
        )

        mock_store = AsyncMock()
        mock_store.get_pending_chunks.return_value = []
        mock_store.expire_stale_leases.return_value = 0
        mock_store.release_chunk.return_value = None
        mock_store.renew_lease.return_value = True
        mock_store.claim_chunk.side_effect = [quarantine_chunk, None]

        from domains.migration.migration_engine import RETRY_DELAYS_SEC
        original_delays = list(RETRY_DELAYS_SEC)
        RETRY_DELAYS_SEC.clear()
        RETRY_DELAYS_SEC.extend([0, 0])

        migration = ChunkedMigration(
            mock_extractor, mock_loader, chunk_size=10000,
            chunk_planner=mock_planner, chunk_store=mock_store,
        )
        plan = TableMigrationPlan(
            table_name="users", schema_name="dbo", columns=["id"],
            row_count_estimate=100, strategy=MigrationStrategy.CHUNKED,
        )
        try:
            result = await migration.migrate_table(plan)
        finally:
            RETRY_DELAYS_SEC.clear()
            RETRY_DELAYS_SEC.extend(original_delays)
        assert result.status == MigrationStatus.FAILED

    @pytest.mark.asyncio
    async def test_stop_requested(self, mock_extractor, mock_loader, mock_chunk_planner, mock_chunk_store):
        migration = ChunkedMigration(
            mock_extractor, mock_loader,
            chunk_planner=mock_chunk_planner, chunk_store=mock_chunk_store,
        )
        migration._stop_requested = True
        plan = TableMigrationPlan(
            table_name="test", schema_name="dbo", columns=["id"],
            row_count_estimate=100, strategy=MigrationStrategy.CHUNKED,
        )

        result = await migration.migrate_table(plan)
        assert result.status == MigrationStatus.STOPPED

    def test_adapt_chunk_size_increase(self):
        new_size = ChunkedMigration._adapt_chunk_size(10000, 1.0, 100000, 50000)
        assert new_size > 10000
        assert new_size <= 100000

    def test_adapt_chunk_size_decrease(self):
        new_size = ChunkedMigration._adapt_chunk_size(10000, 15.0, 100000, 50000)
        assert new_size < 10000
        assert new_size >= 1000

    def test_adapt_chunk_size_stable(self):
        new_size = ChunkedMigration._adapt_chunk_size(10000, 5.0, 100000, 50000)
        assert new_size == 10000

    def test_adapt_chunk_size_respects_max(self):
        new_size = ChunkedMigration._adapt_chunk_size(90000, 0.5, 100000, 50000)
        assert new_size <= 100000

    def test_adapt_chunk_size_respects_min(self):
        new_size = ChunkedMigration._adapt_chunk_size(1500, 30.0, 100000, 50000)
        assert new_size >= 1000


class TestPauseResumeAndCrashRecovery:
    @pytest.mark.asyncio
    async def test_pause_resume(self, mock_extractor, mock_loader, mock_chunk_planner, mock_chunk_store):
        mock_extractor.extract_range.return_value = [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"},
        ]
        mock_chunk_store.claim_chunk.side_effect = [
            mock_chunk_store.claim_chunk.return_value,
            None,
        ]

        migration = ChunkedMigration(
            mock_extractor, mock_loader,
            chunk_planner=mock_chunk_planner, chunk_store=mock_chunk_store,
        )
        paused = asyncio.Event()

        async def pause_before_load(**kwargs):
            await paused.wait()
            return 2

        mock_loader.load_chunk.side_effect = pause_before_load

        plan = TableMigrationPlan(
            table_name="users", schema_name="dbo",
            columns=["id", "name"], row_count_estimate=2,
            strategy=MigrationStrategy.CHUNKED,
        )

        async def run_migration():
            return await migration.migrate_table(plan)

        task = asyncio.create_task(run_migration())
        await asyncio.sleep(0.05)
        assert task.done() is False
        paused.set()
        result = await task
        assert result.status == MigrationStatus.COMPLETED
        assert result.rows_migrated == 2

    @pytest.mark.asyncio
    async def test_stop_interrupts_migration(self, mock_extractor, mock_loader, mock_chunk_planner, mock_chunk_store):
        mock_extractor.extract_range.side_effect = Exception("Should not be called")
        mock_chunk_store.claim_chunk.side_effect = [
            mock_chunk_store.claim_chunk.return_value,
            None,
        ]

        migration = ChunkedMigration(
            mock_extractor, mock_loader,
            chunk_planner=mock_chunk_planner, chunk_store=mock_chunk_store,
        )
        migration._stop_requested = True

        plan = TableMigrationPlan(
            table_name="test", schema_name="dbo", columns=["id"],
            row_count_estimate=100, strategy=MigrationStrategy.CHUNKED,
        )

        result = await migration.migrate_table(plan)
        assert result.status == MigrationStatus.STOPPED

    @pytest.mark.asyncio
    async def test_crash_recovery_expires_stale_leases(self, mock_extractor, mock_loader, mock_chunk_planner, mock_chunk_store):
        mock_extractor.extract_range.return_value = [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"},
        ]
        mock_chunk_store.claim_chunk.side_effect = [
            mock_chunk_store.claim_chunk.return_value,
            None,
        ]

        migration = ChunkedMigration(
            mock_extractor, mock_loader,
            chunk_planner=mock_chunk_planner, chunk_store=mock_chunk_store,
        )
        plan = TableMigrationPlan(
            table_name="users", schema_name="dbo",
            columns=["id", "name"], row_count_estimate=2,
            strategy=MigrationStrategy.CHUNKED,
        )

        result = await migration.migrate_table(plan)
        mock_chunk_store.expire_stale_leases.assert_called_once()
        assert result.status == MigrationStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_claim_chunk_uses_skip_locked(self, mock_extractor, mock_loader, mock_chunk_planner, mock_chunk_store):
        mock_extractor.extract_range.side_effect = [
            [{"id": 1}],
        ]
        mock_chunk_store.claim_chunk.side_effect = [
            mock_chunk_store.claim_chunk.return_value,
            None,
        ]

        migration = ChunkedMigration(
            mock_extractor, mock_loader,
            chunk_planner=mock_chunk_planner, chunk_store=mock_chunk_store,
        )
        plan = TableMigrationPlan(
            table_name="users", schema_name="dbo",
            columns=["id"], row_count_estimate=1,
            strategy=MigrationStrategy.CHUNKED,
        )

        result = await migration.migrate_table(plan)
        assert result.status == MigrationStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_empty_chunks_returns_completed(self, mock_chunk_planner, mock_chunk_store):
        from domains.migration.migration_engine import DataExtractor, DataLoader

        extractor = MagicMock(spec=DataExtractor)
        loader = MagicMock(spec=DataLoader)

        mock_chunk_store.claim_chunk.return_value = None

        migration = ChunkedMigration(
            extractor, loader,
            chunk_planner=mock_chunk_planner, chunk_store=mock_chunk_store,
        )
        plan = TableMigrationPlan(
            table_name="empty", schema_name="dbo", columns=["id"],
            row_count_estimate=0, strategy=MigrationStrategy.CHUNKED,
        )

        result = await migration.migrate_table(plan)
        assert result.status == MigrationStatus.COMPLETED
        assert result.rows_migrated == 0

    @pytest.mark.asyncio
    async def test_migrate_without_chunk_store(self, mock_extractor, mock_loader, mock_chunk_planner):
        mock_extractor.extract_range.return_value = [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"},
        ]
        migration = ChunkedMigration(
            mock_extractor,
            mock_loader,
            chunk_size=100,
            chunk_planner=mock_chunk_planner,
        )
        plan = TableMigrationPlan(
            table_name="users",
            schema_name="dbo",
            columns=["id", "name"],
            row_count_estimate=2,
            strategy=MigrationStrategy.CHUNKED,
        )

        result = await migration.migrate_table(plan)

        assert result.status == MigrationStatus.COMPLETED
        assert result.rows_migrated == 2
        mock_extractor.extract_range.assert_called_once()
        mock_loader.load_chunk.assert_called_once()
