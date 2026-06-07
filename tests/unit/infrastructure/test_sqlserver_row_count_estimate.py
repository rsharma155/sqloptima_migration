"""Unit tests for SQL Server row count estimation (DMV + COUNT fallback)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from infrastructure.sqlserver.row_count_estimate import (
    fetch_sqlserver_table_row_estimate,
    reset_sqlserver_row_count_strategy_cache,
)


@pytest.fixture(autouse=True)
def _clear_dmv_cache() -> None:
    reset_sqlserver_row_count_strategy_cache()


@pytest.mark.asyncio
async def test_fetch_row_estimate_from_partitions() -> None:
    connector = AsyncMock()
    connector.execute.return_value = [{"row_count": 12_345}]
    count = await fetch_sqlserver_table_row_estimate(connector, "dbo", "orders")
    assert count == 12_345
    sql = connector.execute.call_args[0][0]
    assert "sys.partitions" in sql
    connector.execute.assert_called_once()


@pytest.mark.asyncio
async def test_fetch_row_estimate_falls_back_to_count_on_dmv_failure() -> None:
    connector = AsyncMock()
    connector.execute.side_effect = [
        Exception("VIEW DATABASE STATE permission was denied"),
        [{"cnt": 42}],
    ]
    count = await fetch_sqlserver_table_row_estimate(connector, "dbo", "orders")
    assert count == 42
    assert connector.execute.call_count == 2
    assert "COUNT(*)" in connector.execute.call_args_list[1][0][0]


@pytest.mark.asyncio
async def test_skips_dmv_after_cached_permission_denial() -> None:
    connector = AsyncMock()
    connector.execute.side_effect = [
        Exception("permission denied"),
        [{"cnt": 10}],
        [{"cnt": 20}],
    ]
    first = await fetch_sqlserver_table_row_estimate(connector, "dbo", "orders")
    second = await fetch_sqlserver_table_row_estimate(connector, "dbo", "customers")
    assert first == 10
    assert second == 20
    assert connector.execute.call_count == 3
    assert "sys.partitions" not in connector.execute.call_args_list[2][0][0]


@pytest.mark.asyncio
async def test_dmv_zero_does_not_trigger_count_fallback() -> None:
    connector = AsyncMock()
    connector.execute.return_value = [{"row_count": 0}]
    count = await fetch_sqlserver_table_row_estimate(connector, "dbo", "empty")
    assert count == 0
    connector.execute.assert_called_once()


@pytest.mark.asyncio
async def test_returns_zero_when_both_strategies_fail() -> None:
    connector = AsyncMock()
    connector.execute.side_effect = Exception("all fail")
    count = await fetch_sqlserver_table_row_estimate(connector, "dbo", "orders")
    assert count == 0
