"""
Module: test_copy_sub_batching.py
Purpose: TDD tests for item 9.3 — copy_from_rows must sub-batch rows so that each
         asyncpg copy_records_to_table call receives at most batch_size rows.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call

import pytest

from infrastructure.postgres.postgres_connector import (
    COPY_BATCH_SIZE,
    PostgresConnectionConfig,
    PostgresConnector,
)


def _make_config(**overrides) -> PostgresConnectionConfig:
    defaults = {
        "host": "localhost",
        "port": 5432,
        "database": "testdb",
        "username": "pg",
        "password": "pg",
        "ssl_mode": None,
    }
    defaults.update(overrides)
    return PostgresConnectionConfig(**defaults)


def _make_connector_with_mock_pool(copy_fn=None):
    """Return a connector whose pool uses a mock copy_records_to_table."""
    config = _make_config()
    connector = PostgresConnector(config)

    # Each pool.acquire() context returns a fresh mock conn
    copy_calls: list[dict] = []

    async def _copy_records(**kwargs):
        copy_calls.append(kwargs)

    mock_conn = AsyncMock()
    mock_conn.copy_records_to_table = _copy_records

    mock_pool = AsyncMock()
    mock_pool.acquire = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    connector._pool = mock_pool
    return connector, copy_calls


class TestCopyBatchSizeConstant:
    def test_copy_batch_size_is_defined(self):
        """COPY_BATCH_SIZE must be importable and be a positive integer."""
        assert isinstance(COPY_BATCH_SIZE, int)
        assert COPY_BATCH_SIZE > 0

    def test_copy_batch_size_value(self):
        """Default COPY_BATCH_SIZE should be 5000."""
        assert COPY_BATCH_SIZE == 5000


class TestCopyFromRowsSubBatching:
    """Item 9.3: copy_from_rows must split rows into sub-batches."""

    @pytest.mark.asyncio
    async def test_small_batch_single_call(self):
        """Fewer rows than batch_size must result in exactly one copy call."""
        connector, copy_calls = _make_connector_with_mock_pool()
        rows = [(i,) for i in range(10)]
        total = await connector.copy_from_rows("t", ["id"], rows, schema="public", batch_size=50)
        assert len(copy_calls) == 1
        assert total == 10

    @pytest.mark.asyncio
    async def test_exact_batch_size_single_call(self):
        """Rows equal to batch_size must result in exactly one copy call."""
        connector, copy_calls = _make_connector_with_mock_pool()
        rows = [(i,) for i in range(100)]
        total = await connector.copy_from_rows("t", ["id"], rows, schema="public", batch_size=100)
        assert len(copy_calls) == 1
        assert total == 100

    @pytest.mark.asyncio
    async def test_rows_split_into_multiple_batches(self):
        """More rows than batch_size must result in multiple copy calls."""
        connector, copy_calls = _make_connector_with_mock_pool()
        rows = [(i,) for i in range(250)]
        total = await connector.copy_from_rows("t", ["id"], rows, schema="public", batch_size=100)
        # 250 rows / 100 batch_size = 3 calls (100, 100, 50)
        assert len(copy_calls) == 3
        assert total == 250

    @pytest.mark.asyncio
    async def test_each_batch_has_correct_size(self):
        """Each sub-batch must have at most batch_size rows."""
        connector, copy_calls = _make_connector_with_mock_pool()
        rows = [(i,) for i in range(350)]
        batch_size = 100
        await connector.copy_from_rows("t", ["id"], rows, schema="public", batch_size=batch_size)
        # All batches except possibly the last must be exactly batch_size
        for i, c in enumerate(copy_calls[:-1]):
            assert len(c["records"]) == batch_size, (
                f"Batch {i} has {len(c['records'])} rows, expected {batch_size}"
            )
        # Last batch has the remainder
        assert len(copy_calls[-1]["records"]) == 350 % batch_size or len(copy_calls[-1]["records"]) == batch_size

    @pytest.mark.asyncio
    async def test_rows_content_preserved_across_batches(self):
        """All rows must appear exactly once across all copy calls."""
        connector, copy_calls = _make_connector_with_mock_pool()
        rows = [(i, f"name_{i}") for i in range(120)]
        await connector.copy_from_rows("t", ["id", "name"], rows, schema="s", batch_size=50)

        all_records = []
        for c in copy_calls:
            all_records.extend(c["records"])
        assert all_records == rows

    @pytest.mark.asyncio
    async def test_empty_rows_returns_zero(self):
        """copy_from_rows with empty rows list must return 0 and make no copy calls."""
        connector, copy_calls = _make_connector_with_mock_pool()
        total = await connector.copy_from_rows("t", ["id"], [], schema="public", batch_size=100)
        assert total == 0
        assert copy_calls == []

    @pytest.mark.asyncio
    async def test_default_batch_size_is_copy_batch_size(self):
        """When batch_size is not specified, the module-level COPY_BATCH_SIZE must be used."""
        import inspect
        from infrastructure.postgres.postgres_connector import PostgresConnector
        sig = inspect.signature(PostgresConnector.copy_from_rows)
        params = sig.parameters
        assert "batch_size" in params, "copy_from_rows must have a batch_size parameter"
        default = params["batch_size"].default
        assert default == COPY_BATCH_SIZE, (
            f"Default batch_size must be COPY_BATCH_SIZE={COPY_BATCH_SIZE}, got {default}"
        )

    @pytest.mark.asyncio
    async def test_schema_forwarded_to_copy_records_to_table(self):
        """schema_name must be forwarded to every copy_records_to_table call."""
        connector, copy_calls = _make_connector_with_mock_pool()
        rows = [(i,) for i in range(200)]
        await connector.copy_from_rows("tbl", ["id"], rows, schema="myschema", batch_size=100)
        for c in copy_calls:
            assert c.get("schema_name") == "myschema", (
                f"schema_name not forwarded: {c}"
            )

    @pytest.mark.asyncio
    async def test_table_forwarded_to_copy_records_to_table(self):
        """table_name must be forwarded to every copy_records_to_table call."""
        connector, copy_calls = _make_connector_with_mock_pool()
        rows = [(i,) for i in range(50)]
        await connector.copy_from_rows("my_table", ["id"], rows, batch_size=25)
        for c in copy_calls:
            assert c.get("table_name") == "my_table", (
                f"table_name not forwarded: {c}"
            )
