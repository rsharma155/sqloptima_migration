"""Tests for cast-safe column resolution during Go dispatch."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from application.go_engine_migration.go_migration_column_resolver import (
    resolve_source_table_columns,
)


@pytest.mark.asyncio
async def test_resolve_columns_uses_catalog_not_select_star():
    connector = AsyncMock()
    connector.execute = AsyncMock(
        return_value=[
            {"column_name": "id"},
            {"column_name": "col_sql_variant"},
            {"column_name": "col_hierarchyid"},
        ],
    )

    cols = await resolve_source_table_columns(
        connector, "dbo", "dt_MiscTypes", ["*"],
    )

    assert cols == ["id", "col_sql_variant", "col_hierarchyid"]
    sql = connector.execute.call_args[0][0]
    assert "sys.columns" in sql
    assert "SELECT TOP 1 *" not in sql


@pytest.mark.asyncio
async def test_resolve_columns_returns_explicit_list_unchanged():
    connector = AsyncMock()
    cols = await resolve_source_table_columns(
        connector, "dbo", "Orders", ["OrderId", "Total"],
    )
    assert cols == ["OrderId", "Total"]
    connector.execute.assert_not_called()
