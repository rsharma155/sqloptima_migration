"""
Module: tests/unit/replicator/test_watermark_provider_dba_fixes.py
Purpose: TDD tests for DBA feedback fixes:
         2.1 — WatermarkProvider cannot detect DELETE operations.
         2.2 — Resume position is a hardcoded placeholder.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import pytest

from apps.replicator.capture.models import ChangeOperation, LsnPosition, TableInfo
from apps.replicator.capture.providers.watermark_provider import WatermarkProvider


class _ConcreteWatermarkProvider(WatermarkProvider):
    """Testable subclass that injects rows directly."""

    def __init__(self, rows=None):
        super().__init__()
        self._rows = rows or []

    async def _execute_query(self, schema, table_name, columns, watermark_column, last_value, batch_size):
        return self._rows[:batch_size]


def _make_table(soft_delete_col: str | None = None, watermark_col: str = "modified_at") -> TableInfo:
    return TableInfo(
        schema_name="dbo",
        table_name="users",
        columns=["id", "name", watermark_col] + ([soft_delete_col] if soft_delete_col else []),
        watermark_column=watermark_col,
        soft_delete_column=soft_delete_col,
    )


class TestResumePositionTracking:
    """
    Issue 2.2: new_position must reflect the actual max watermark value from the
    batch, not a hardcoded zero LSN placeholder.
    """

    @pytest.mark.asyncio
    async def test_new_position_tracks_max_watermark(self):
        rows = [
            {"id": 1, "name": "Alice", "modified_at": "2026-01-01T10:00:00"},
            {"id": 2, "name": "Bob",   "modified_at": "2026-01-02T12:00:00"},
        ]
        provider = _ConcreteWatermarkProvider(rows=rows)
        table = _make_table(watermark_col="modified_at")
        batch = await provider.capture_changes(table, last_position=None)
        # new_position must NOT be the hardcoded zero LSN
        zero_lsn = LsnPosition.from_string("0x00000000:00000000:0000").serialize()
        assert batch.new_position is not None
        assert batch.new_position.serialize() != zero_lsn, (
            "new_position is still the hardcoded zero LSN — fix 2.2 not applied"
        )
        # Must contain the max watermark value
        pos_str = batch.new_position.serialize().decode()
        assert "2026-01-02T12:00:00" in pos_str or "2026-01-02" in pos_str

    @pytest.mark.asyncio
    async def test_empty_batch_preserves_last_position(self):
        provider = _ConcreteWatermarkProvider(rows=[])
        table = _make_table()
        last_pos = b"2026-01-01T00:00:00"
        batch = await provider.capture_changes(table, last_position=last_pos)
        assert batch.new_position is not None
        # On empty batch, preserve the incoming position
        assert batch.new_position.serialize() == last_pos


class TestSoftDeleteDetection:
    """
    Issue 2.1: Watermark provider can only detect INSERTs/UPDATEs via polling.
    Short-term fix: when a table has a soft-delete column, emit DELETE events
    for rows where soft_delete_column = True/1.
    """

    @pytest.mark.asyncio
    async def test_hard_delete_limitation_documented(self):
        """Without soft-delete column, all events are INSERT (documented limitation)."""
        rows = [{"id": 1, "name": "Alice", "modified_at": "2026-01-01"}]
        provider = _ConcreteWatermarkProvider(rows=rows)
        table = _make_table(soft_delete_col=None)
        batch = await provider.capture_changes(table, last_position=None)
        # All events are INSERT since no soft-delete column — this is expected
        for event in batch.changes:
            assert event.operation == ChangeOperation.INSERT

    @pytest.mark.asyncio
    async def test_soft_deleted_rows_emitted_as_delete(self):
        """Rows with is_deleted=True must be emitted as ChangeOperation.DELETE."""
        rows = [
            {"id": 1, "name": "Alice", "modified_at": "2026-01-01", "is_deleted": False},
            {"id": 2, "name": "Bob",   "modified_at": "2026-01-02", "is_deleted": True},
        ]
        provider = _ConcreteWatermarkProvider(rows=rows)
        table = _make_table(soft_delete_col="is_deleted")
        batch = await provider.capture_changes(table, last_position=None)
        ops = [e.operation for e in batch.changes]
        assert ChangeOperation.DELETE in ops, (
            "Soft-deleted rows (is_deleted=True) must produce DELETE events — fix 2.1 not applied"
        )
        # Non-deleted rows stay as INSERT/UPDATE
        assert ChangeOperation.INSERT in ops

    @pytest.mark.asyncio
    async def test_soft_deleted_event_uses_before_values(self):
        """DELETE events must carry the row in before_values, not after_values."""
        rows = [{"id": 99, "name": "Deleted", "modified_at": "2026-01-01", "is_deleted": True}]
        provider = _ConcreteWatermarkProvider(rows=rows)
        table = _make_table(soft_delete_col="is_deleted")
        batch = await provider.capture_changes(table, last_position=None)
        delete_events = [e for e in batch.changes if e.operation == ChangeOperation.DELETE]
        assert len(delete_events) == 1
        assert delete_events[0].before_values is not None
        assert delete_events[0].before_values.get("id") == 99
