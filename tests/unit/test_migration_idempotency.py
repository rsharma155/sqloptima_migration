"""Idempotent re-run safety tests (§11.4)."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from domains.migration.migration_engine import DataLoader


@pytest.mark.asyncio
async def test_loader_uses_idempotent_write_path():
    connector = AsyncMock()
    connector.copy_with_idempotent_write = AsyncMock(return_value=2)

    loader = DataLoader(connector, idempotent=True, conflict_columns=["id"])
    count = await loader.load_chunk(
        schema="public",
        table="users",
        columns=["id", "name"],
        rows=[(1, "a"), (2, "b")],
    )
    assert count == 2
    connector.copy_with_idempotent_write.assert_awaited_once()
    kwargs = connector.copy_with_idempotent_write.await_args.kwargs
    assert kwargs["conflict_columns"] == ["id"]


@pytest.mark.asyncio
async def test_loader_idempotent_rerun_same_chunk_no_duplicate_path():
    """Second load of the same rows must use the same UPSERT path (not plain COPY)."""
    connector = AsyncMock()
    connector.copy_with_idempotent_write = AsyncMock(return_value=1)

    loader = DataLoader(connector, idempotent=True, conflict_columns=["id"])
    rows = [(42, "alice")]
    await loader.load_chunk("public", "users", ["id", "name"], rows)
    await loader.load_chunk("public", "users", ["id", "name"], rows)

    assert connector.copy_with_idempotent_write.await_count == 2
    assert connector.copy_from_rows.await_count == 0


@pytest.mark.asyncio
async def test_chunked_migration_double_run_idempotent(tmp_path):
    """Full ChunkedMigration re-run over the same plan uses idempotent writes (§11.4)."""
    from uuid import uuid4

    from domains.chunking.chunk_planner import ChunkBoundary, ChunkPlan, ChunkingResult
    from domains.migration.migration_engine import (
        ChunkedMigration,
        MigrationStatus,
        MigrationStrategy,
        TableMigrationPlan,
    )
    from domains.migration.checkpoint_store import MigrationCheckpointStore

    extractor = AsyncMock()
    extractor.extract_range = AsyncMock(
        return_value=[{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
    )
    connector = AsyncMock()
    connector.copy_with_idempotent_write = AsyncMock(return_value=2)
    loader = DataLoader(connector, idempotent=True, conflict_columns=["id"])

    def make_chunk():
        return ChunkPlan(
            chunk_id=uuid4(),
            table_schema="dbo",
            table_name="users",
            column_name="id",
            boundary=ChunkBoundary(start=1, end=100),
        )

    planner = AsyncMock()
    planner.plan_table = AsyncMock(
        side_effect=[
            ChunkingResult(chunks=[make_chunk()], total_rows_estimate=2),
            ChunkingResult(chunks=[make_chunk()], total_rows_estimate=2),
        ]
    )

    cps = MigrationCheckpointStore(str(tmp_path / "cp.db"))
    await cps.initialize()

    migration = ChunkedMigration(
        extractor,
        loader,
        chunk_size=100,
        chunk_planner=planner,
        checkpoint_store=cps,
        idempotent_writes=True,
        conflict_columns=["id"],
    )
    plan = TableMigrationPlan(
        schema_name="dbo",
        table_name="users",
        target_schema="public",
        columns=["id", "name"],
        row_count_estimate=2,
        strategy=MigrationStrategy.CHUNKED,
        chunk_size=100,
    )

    first = await migration.migrate_table(plan)
    second = await migration.migrate_table(plan)

    assert first.status == MigrationStatus.COMPLETED
    assert second.status == MigrationStatus.COMPLETED
    assert connector.copy_with_idempotent_write.await_count >= 2
    assert connector.copy_from_rows.await_count == 0
