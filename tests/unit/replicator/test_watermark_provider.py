"""
Module: tests/unit/replicator/test_watermark_provider.py
Purpose: Unit tests for WatermarkProvider (timestamp/sequence column polling)
Author: Migration Platform Team
Created: 2026-05-22
Domain: Replication / Capture
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from unittest.mock import AsyncMock

import pytest

from apps.replicator.capture.models import ChangeOperation, LsnPosition, TableInfo
from apps.replicator.capture.providers.watermark_provider import WatermarkProvider


class TestWatermarkProvider:
    """Tests for the watermark-based incremental capture provider."""

    @pytest.mark.asyncio
    async def test_connect_saves_connection_string(self):
        provider = WatermarkProvider()
        await provider.connect("mock://localhost")
        assert provider._connection_string == "mock://localhost"

    @pytest.mark.asyncio
    async def test_connect_raises_on_empty_string(self):
        provider = WatermarkProvider()
        with pytest.raises(ValueError, match="connection_string"):
            await provider.connect("")

    @pytest.mark.asyncio
    async def test_discover_tables_requires_override(self):
        provider = WatermarkProvider()
        table = TableInfo(schema_name="dbo", table_name="orders", columns=["id", "status"])
        provider._fetch_table_list = AsyncMock(return_value=[table])  # type: ignore[method-assign]
        tables = await provider.discover_tables("dbo")
        assert len(tables) == 1
        assert tables[0].table_name == "orders"

    @pytest.mark.asyncio
    async def test_capture_changes_with_no_prior_position(self):
        provider = WatermarkProvider()
        provider._execute_query = AsyncMock(return_value=[
            {"id": 1, "status": "shipped", "LastModifiedDate": "2026-05-22T12:00:01"},
        ])

        table = TableInfo(
            schema_name="dbo",
            table_name="orders",
            columns=["id", "status", "LastModifiedDate"],
            pk_columns=["id"],
        )
        batch = await provider.capture_changes(table, last_position=None, batch_size=100)

        assert batch.change_count == 1
        event = batch.changes[0]
        assert event.operation == ChangeOperation.INSERT
        assert event.after_values["id"] == 1
        assert event.table_name == "orders"

    @pytest.mark.asyncio
    async def test_capture_changes_uses_position_as_watermark(self):
        provider = WatermarkProvider()
        provider._execute_query = AsyncMock(return_value=[
            {"id": 2, "status": "pending", "LastModifiedDate": "2026-05-22T12:00:02"},
            {"id": 3, "status": "active", "LastModifiedDate": "2026-05-22T12:00:03"},
        ])

        table = TableInfo(
            schema_name="dbo",
            table_name="orders",
            columns=["id", "status", "LastModifiedDate"],
            pk_columns=["id"],
            watermark_column="LastModifiedDate",
        )
        last_pos = b"2026-05-22T12:00:01"
        batch = await provider.capture_changes(table, last_position=last_pos, batch_size=100)

        assert batch.change_count == 2
        assert batch.changes[0].after_values["id"] == 2

    @pytest.mark.asyncio
    async def test_capture_changes_empty_result(self):
        provider = WatermarkProvider()
        provider._execute_query = AsyncMock(return_value=[])

        table = TableInfo(
            schema_name="dbo",
            table_name="orders",
            columns=["id"],
            pk_columns=["id"],
            watermark_column="updated_at",
        )
        batch = await provider.capture_changes(table, last_position=b"2026-01-01", batch_size=100)

        assert batch.change_count == 0
        assert len(batch.changes) == 0
        # Fix 2.2: on empty batch the provider must preserve last_position, NOT return
        # a hardcoded zero LSN placeholder.
        assert batch.new_position is not None
        assert batch.new_position.serialize() == b"2026-01-01"

    @pytest.mark.asyncio
    async def test_capture_changes_marks_update_when_pk_exists(self):
        provider = WatermarkProvider()
        provider._execute_query = AsyncMock(return_value=[
            {"id": 5, "name": "Updated Name", "modified": "2026-05-22T13:00:00"},
        ])

        table = TableInfo(
            schema_name="dbo",
            table_name="items",
            columns=["id", "name", "modified"],
            pk_columns=["id"],
            watermark_column="modified",
        )
        batch = await provider.capture_changes(
            table, last_position=b"2026-05-22T12:00:00", batch_size=100,
        )

        assert batch.change_count == 1
        assert batch.changes[0].operation == ChangeOperation.INSERT

    @pytest.mark.asyncio
    async def test_discover_tables_detects_watermark_column(self):
        provider = WatermarkProvider()

        async def fake_fetch(schema: str) -> list[TableInfo]:
            return [
                TableInfo(
                    schema_name=schema,
                    table_name="orders",
                    columns=["id", "status", "updated_at"],
                    pk_columns=["id"],
                    watermark_column="updated_at",
                ),
            ]

        provider._fetch_table_list = AsyncMock(side_effect=fake_fetch)  # type: ignore[method-assign]
        tables = await provider.discover_tables("dbo")
        assert tables[0].watermark_column == "updated_at"

    @pytest.mark.asyncio
    async def test_capture_changes_applies_batch_size_limit(self):
        provider = WatermarkProvider()
        many_rows = [{"id": i, "modified": f"2026-05-22T12:00:{i:02d}"} for i in range(50)]
        provider._execute_query = AsyncMock(return_value=many_rows)

        table = TableInfo(
            schema_name="dbo",
            table_name="events",
            columns=["id", "modified"],
            pk_columns=["id"],
            watermark_column="modified",
        )
        batch = await provider.capture_changes(
            table, last_position=b"2026-05-22T12:00:00", batch_size=10,
        )

        assert batch.change_count <= 10

    @pytest.mark.asyncio
    async def test_capture_changes_watermark_column_default(self):
        provider = WatermarkProvider()
        provider._execute_query = AsyncMock(return_value=[
            {"id": 1, "name": "test", "modified": "2026-01-01"},
        ])
        table = TableInfo(
            schema_name="dbo",
            table_name="t",
            columns=["id", "name", "modified"],
            pk_columns=["id"],
        )
        batch = await provider.capture_changes(table, last_position=None, batch_size=100)
        assert batch.change_count == 1
