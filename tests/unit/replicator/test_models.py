"""
Module: tests/unit/replicator/test_models.py
Purpose: Unit tests for replication domain models (ChangeEvent, Watermark, LsnPosition)
Author: Migration Platform Team
Created: 2026-05-22
Domain: Replication / Capture
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from datetime import UTC, datetime

from apps.replicator.capture.models import (
    CaptureBatch,
    ChangeEvent,
    ChangeOperation,
    LsnPosition,
    SnapshotResult,
    TableInfo,
    Watermark,
)


class TestChangeOperation:
    def test_has_expected_values(self):
        assert ChangeOperation.INSERT == "INSERT"
        assert ChangeOperation.UPDATE == "UPDATE"
        assert ChangeOperation.DELETE == "DELETE"
        assert ChangeOperation.UPDATE_MERGE == "UPDATEMERGE"


class TestLsnPosition:
    def test_from_string_parses_correctly(self):
        lsn = LsnPosition.from_string("0x00001234:0000ABCD:0001")
        assert lsn.segment1 == 0x00001234
        assert lsn.segment2 == 0x0000ABCD
        assert lsn.segment3 == 0x0001

    def test_from_string_without_prefix(self):
        lsn = LsnPosition.from_string("00001234:0000ABCD:0001")
        assert lsn.segment1 == 0x00001234

    def test_to_string_roundtrip(self):
        raw = "0x00001234:0000ABCD:0001"
        lsn = LsnPosition.from_string(raw)
        assert lsn.to_string() == raw

    def test_ordering(self):
        a = LsnPosition.from_string("0x00000000:00000000:0001")
        b = LsnPosition.from_string("0x00000000:00000000:0002")
        c = LsnPosition.from_string("0x00000001:00000000:0000")
        assert a < b
        assert b < c
        assert a < c

    def test_equality(self):
        a = LsnPosition.from_string("0x00001234:0000ABCD:0001")
        b = LsnPosition.from_string("0x00001234:0000ABCD:0001")
        assert a == b

    def test_serialization(self):
        lsn = LsnPosition(segment1=0x1234, segment2=0xABCD, segment3=1)
        assert lsn.serialize() == b"\x00\x00\x124\x00\x00\xab\xcd\x00\x00\x00\x01"


class TestChangeEvent:
    def test_minimal_change_event(self):
        event = ChangeEvent(
            table_schema="dbo",
            table_name="users",
            operation=ChangeOperation.INSERT,
            after_values={"id": 1, "name": "Alice"},
        )
        assert event.event_id is not None
        assert event.table_schema == "dbo"
        assert event.table_name == "users"
        assert event.operation == ChangeOperation.INSERT
        assert event.after_values == {"id": 1, "name": "Alice"}
        assert event.before_values is None

    def test_full_change_event(self):
        ts = datetime.now(UTC)
        lsn = LsnPosition.from_string("0x00001234:0000ABCD:0001")
        event = ChangeEvent(
            table_schema="sales",
            table_name="orders",
            operation=ChangeOperation.UPDATE,
            before_values={"id": 42, "status": "pending"},
            after_values={"id": 42, "status": "shipped"},
            lsn=lsn,
            source_timestamp=ts,
            source_host="sql-01",
            source_database="salesdb",
            transaction_id="0000:0000abcd",
        )
        assert event.table_schema == "sales"
        assert event.operation == ChangeOperation.UPDATE
        assert event.lsn == lsn
        assert event.source_host == "sql-01"
        assert len(event.before_values) == 2

    def test_delete_event_has_no_after(self):
        event = ChangeEvent(
            table_schema="dbo",
            table_name="users",
            operation=ChangeOperation.DELETE,
            before_values={"id": 1},
        )
        assert event.after_values is None

    def test_event_id_is_unique(self):
        e1 = ChangeEvent(
            table_schema="dbo", table_name="t",
            operation=ChangeOperation.INSERT, after_values={"id": 1},
        )
        e2 = ChangeEvent(
            table_schema="dbo", table_name="t",
            operation=ChangeOperation.INSERT, after_values={"id": 1},
        )
        assert e1.event_id != e2.event_id


class TestWatermark:
    def test_watermark_creation(self):
        wm = Watermark(
            table_schema="dbo",
            table_name="orders",
            watermark_column="LastModifiedDate",
            last_value="2026-05-22T10:00:00",
        )
        assert wm.table_schema == "dbo"
        assert wm.last_value == "2026-05-22T10:00:00"

    def test_watermark_default_batch_size(self):
        wm = Watermark(table_schema="dbo", table_name="t", watermark_column="ts", last_value="0")
        assert wm.batch_size == 1000


class TestTableInfo:
    def test_table_info_creation(self):
        info = TableInfo(schema_name="dbo", table_name="orders", columns=["id", "name", "status"])
        assert info.schema_name == "dbo"
        assert info.pk_columns == []  # default

    def test_table_info_with_pk(self):
        info = TableInfo(
            schema_name="dbo", table_name="users",
            columns=["id", "email"], pk_columns=["id"],
        )
        assert info.pk_columns == ["id"]

    def test_qualified_name(self):
        info = TableInfo(schema_name="sales", table_name="orders", columns=["id"])
        assert info.qualified_name == "sales.orders"


class TestCaptureBatch:
    def test_empty_batch(self):
        lsn = LsnPosition.from_string("0x00000000:00000000:0000")
        batch = CaptureBatch(changes=[], new_position=lsn)
        assert len(batch.changes) == 0
        assert batch.new_position == lsn

    def test_batch_with_changes(self):
        changes = [
            ChangeEvent(
                table_schema="dbo", table_name="t",
                operation=ChangeOperation.INSERT, after_values={"id": 1},
            ),
            ChangeEvent(
                table_schema="dbo", table_name="t",
                operation=ChangeOperation.UPDATE, after_values={"id": 2},
            ),
        ]
        lsn = LsnPosition.from_string("0x00001234:0000ABCD:0005")
        batch = CaptureBatch(changes=changes, new_position=lsn)
        assert len(batch.changes) == 2
        assert batch.change_count == 2


class TestSnapshotResult:
    def test_snapshot_result_defaults(self):
        result = SnapshotResult(table_name="orders", rows_captured=1000)
        assert result.duration_seconds == 0.0
        assert result.errors == []

    def test_snapshot_result_with_errors(self):
        result = SnapshotResult(
            table_name="orders", rows_captured=500,
            duration_seconds=10.5, errors=["timeout"],
        )
        assert result.rows_captured == 500
        assert result.errors == ["timeout"]
        assert result.success is False
