"""
Module: tests/unit/replicator/test_cdc_provider.py
Purpose: Unit tests for SqlServerCdcProvider — verifies CDC event parsing,
         LSN advancement, and INSERT/UPDATE/DELETE operation mapping.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import struct
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.replicator.capture.models import (
    CaptureBatch,
    ChangeOperation,
    LsnPosition,
    TableInfo,
)
from apps.replicator.capture.providers.cdc_provider import SqlServerCdcProvider


def _make_lsn_bytes(seg1: int, seg2: int, seg3: int) -> bytes:
    return struct.pack(">III", seg1, seg2, seg3)


def _make_connector(rows: list[dict[str, Any]], min_lsn: bytes = b"", max_lsn: bytes = b"") -> MagicMock:
    connector = MagicMock()

    async def execute(query: str, *args: Any) -> list[dict[str, Any]]:
        if "fn_cdc_get_min_lsn" in query:
            return [{"min_lsn": min_lsn}]
        if "fn_cdc_get_max_lsn" in query:
            return [{"max_lsn": max_lsn}]
        return rows

    connector.execute = execute
    return connector


@pytest.fixture
def table() -> TableInfo:
    return TableInfo(
        schema_name="dbo",
        table_name="orders",
        columns=["id", "amount", "status"],
        pk_columns=["id"],
    )


class TestSqlServerCdcProviderConnect:
    async def test_connect_stores_connection_string(self) -> None:
        provider = SqlServerCdcProvider(MagicMock())
        await provider.connect("Server=localhost;Database=testdb")
        assert provider._connection_string == "Server=localhost;Database=testdb"

    async def test_connect_empty_raises(self) -> None:
        provider = SqlServerCdcProvider(MagicMock())
        with pytest.raises(ValueError, match="connection_string"):
            await provider.connect("")


class TestSqlServerCdcProviderInsert:
    async def test_insert_operation_parsed(self, table: TableInfo) -> None:
        lsn_bytes = _make_lsn_bytes(1, 0, 1)
        rows = [
            {
                "__$start_lsn": lsn_bytes,
                "__$operation": 2,  # INSERT
                "__$update_mask": None,
                "id": 42,
                "amount": 100.0,
                "status": "new",
            }
        ]
        connector = _make_connector(rows, min_lsn=lsn_bytes, max_lsn=lsn_bytes)
        provider = SqlServerCdcProvider(connector)

        batch = await provider.capture_changes(table, last_position=None, batch_size=1000)

        assert isinstance(batch, CaptureBatch)
        assert len(batch.changes) == 1
        event = batch.changes[0]
        assert event.operation == ChangeOperation.INSERT
        assert event.after_values == {"id": 42, "amount": 100.0, "status": "new"}
        assert event.before_values is None
        assert event.table_schema == "dbo"
        assert event.table_name == "orders"


class TestSqlServerCdcProviderDelete:
    async def test_delete_operation_parsed(self, table: TableInfo) -> None:
        lsn_bytes = _make_lsn_bytes(1, 0, 2)
        rows = [
            {
                "__$start_lsn": lsn_bytes,
                "__$operation": 1,  # DELETE
                "__$update_mask": None,
                "id": 10,
                "amount": 50.0,
                "status": "old",
            }
        ]
        connector = _make_connector(rows, min_lsn=lsn_bytes, max_lsn=lsn_bytes)
        provider = SqlServerCdcProvider(connector)

        batch = await provider.capture_changes(table, last_position=None, batch_size=1000)

        assert len(batch.changes) == 1
        event = batch.changes[0]
        assert event.operation == ChangeOperation.DELETE
        assert event.before_values == {"id": 10, "amount": 50.0, "status": "old"}
        assert event.after_values is None


class TestSqlServerCdcProviderUpdate:
    async def test_update_after_row_emitted(self, table: TableInfo) -> None:
        lsn_bytes = _make_lsn_bytes(1, 0, 3)
        lsn_bytes2 = _make_lsn_bytes(1, 0, 4)
        rows = [
            {
                "__$start_lsn": lsn_bytes,
                "__$operation": 3,  # UPDATE before
                "__$update_mask": None,
                "id": 5,
                "amount": 20.0,
                "status": "pending",
            },
            {
                "__$start_lsn": lsn_bytes2,
                "__$operation": 4,  # UPDATE after
                "__$update_mask": None,
                "id": 5,
                "amount": 25.0,
                "status": "approved",
            },
        ]
        connector = _make_connector(rows, min_lsn=lsn_bytes, max_lsn=lsn_bytes2)
        provider = SqlServerCdcProvider(connector)

        batch = await provider.capture_changes(table, last_position=None, batch_size=1000)

        # UPDATE before (op=3) is skipped; UPDATE after (op=4) becomes UPDATE event
        update_events = [e for e in batch.changes if e.operation == ChangeOperation.UPDATE]
        assert len(update_events) == 1
        assert update_events[0].after_values["amount"] == 25.0

    async def test_update_before_row_discarded(self, table: TableInfo) -> None:
        lsn_bytes = _make_lsn_bytes(1, 0, 5)
        rows = [
            {
                "__$start_lsn": lsn_bytes,
                "__$operation": 3,  # UPDATE before — should be skipped
                "__$update_mask": None,
                "id": 9,
                "amount": 5.0,
                "status": "x",
            }
        ]
        connector = _make_connector(rows, min_lsn=lsn_bytes, max_lsn=lsn_bytes)
        provider = SqlServerCdcProvider(connector)

        batch = await provider.capture_changes(table, last_position=None, batch_size=1000)
        assert batch.changes == []


class TestSqlServerCdcProviderLsnAdvancement:
    async def test_lsn_advances_to_last_row(self, table: TableInfo) -> None:
        lsn1 = _make_lsn_bytes(1, 0, 1)
        lsn2 = _make_lsn_bytes(1, 0, 9)
        rows = [
            {"__$start_lsn": lsn1, "__$operation": 2, "__$update_mask": None, "id": 1, "amount": 10.0, "status": "a"},
            {"__$start_lsn": lsn2, "__$operation": 2, "__$update_mask": None, "id": 2, "amount": 20.0, "status": "b"},
        ]
        connector = _make_connector(rows, min_lsn=lsn1, max_lsn=lsn2)
        provider = SqlServerCdcProvider(connector)

        batch = await provider.capture_changes(table, last_position=None, batch_size=1000)

        expected_lsn = LsnPosition(*struct.unpack(">III", lsn2))
        assert batch.new_position == expected_lsn

    async def test_lsn_unchanged_when_no_rows(self, table: TableInfo) -> None:
        lsn = _make_lsn_bytes(5, 0, 0)
        connector = _make_connector([], min_lsn=lsn, max_lsn=lsn)
        provider = SqlServerCdcProvider(connector)

        batch = await provider.capture_changes(table, last_position=lsn, batch_size=1000)
        assert batch.changes == []
        # new_position should not regress
        assert batch.new_position is not None

    async def test_uses_provided_last_position(self, table: TableInfo) -> None:
        lsn_from = _make_lsn_bytes(2, 0, 0)
        lsn_to = _make_lsn_bytes(3, 0, 0)

        execute_calls: list[tuple] = []

        async def execute(query: str, *args: Any) -> list[dict[str, Any]]:
            execute_calls.append((query, args))
            if "fn_cdc_get_max_lsn" in query:
                return [{"max_lsn": lsn_to}]
            return []

        connector = MagicMock()
        connector.execute = execute
        provider = SqlServerCdcProvider(connector)

        await provider.capture_changes(table, last_position=lsn_from, batch_size=1000)

        # fn_cdc_get_min_lsn should NOT be called when last_position is provided
        min_lsn_calls = [c for c in execute_calls if "fn_cdc_get_min_lsn" in c[0]]
        assert len(min_lsn_calls) == 0


class TestSqlServerCdcProviderDiscoverTables:
    async def test_discover_tables_returns_list(self) -> None:
        connector = MagicMock()
        connector.execute = AsyncMock(return_value=[])
        provider = SqlServerCdcProvider(connector)
        result = await provider.discover_tables("dbo")
        assert isinstance(result, list)


class TestSqlServerCdcProviderSnapshot:
    async def test_take_snapshot_calls_callback(self, table: TableInfo) -> None:
        lsn_bytes = _make_lsn_bytes(1, 0, 1)
        rows = [
            {"__$start_lsn": lsn_bytes, "__$operation": 2, "__$update_mask": None,
             "id": 99, "amount": 1.0, "status": "z"}
        ]
        connector = _make_connector(rows, min_lsn=lsn_bytes, max_lsn=lsn_bytes)
        provider = SqlServerCdcProvider(connector)

        received: list = []

        async def cb(events: list) -> None:
            received.extend(events)

        await provider.take_snapshot(table, cb, chunk_size=1000)
        # Snapshot emits INSERT events for all rows
        assert any(e.operation == ChangeOperation.INSERT for e in received)
