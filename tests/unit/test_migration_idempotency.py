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
