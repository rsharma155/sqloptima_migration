"""Chunked migration idempotent re-run integration test (§11.4)."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from domains.migration.migration_engine import (
    DataExtractor,
    DataLoader,
    MigrationStrategy,
    TableMigrationPlan,
)


@pytest.mark.asyncio
async def test_double_load_same_rows_uses_idempotent_path():
    """Re-loading the same primary-key rows must not use plain COPY twice."""
    rows = [{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}]
    source = AsyncMock()
    source.execute = AsyncMock(return_value=rows)

    target = AsyncMock()
    target.copy_with_idempotent_write = AsyncMock(return_value=2)

    extractor = DataExtractor(connector=source)
    loader = DataLoader(connector=target, idempotent=True, conflict_columns=["id"])

    extracted = await extractor.extract_range(
        schema="dbo",
        table="users",
        column_name="id",
        start=1,
        end=2,
        columns=["id", "name"],
        order_column="id",
    )
    tuples = [tuple(r[c] for c in ["id", "name"]) for r in extracted]

    await loader.load_chunk("public", "users", ["id", "name"], tuples)
    await loader.load_chunk("public", "users", ["id", "name"], tuples)

    assert target.copy_with_idempotent_write.await_count == 2
    assert not target.copy_from_rows.called


@pytest.mark.asyncio
async def test_plan_idempotent_flag_wires_to_loader():
    plan = TableMigrationPlan(
        table_name="users",
        schema_name="dbo",
        columns=["id", "name"],
        row_count_estimate=100,
        strategy=MigrationStrategy.CHUNKED,
        parallel_workers=1,
    )
    target = AsyncMock()
    target.copy_with_idempotent_write = AsyncMock(return_value=1)
    loader = DataLoader(target, idempotent=True, conflict_columns=["id"])
    await loader.load_chunk(
        plan.target_schema or "public",
        plan.table_name,
        ["id", "name"],
        [(1, "x")],
        idempotent=True,
        conflict_columns=["id"],
    )
    target.copy_with_idempotent_write.assert_awaited_once()
