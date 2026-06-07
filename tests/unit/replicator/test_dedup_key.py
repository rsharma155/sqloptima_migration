"""
Module: tests/unit/replicator/test_dedup_key.py
Purpose: Unit tests for DedupKey — the idempotency-key value object that yields
         a stable dedup identity for a ChangeEvent, with or without an LSN.
Domain: Replication / Apply
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from apps.replicator.apply.dedup_key import DedupKey
from apps.replicator.capture.models import ChangeEvent, ChangeOperation, LsnPosition


def _event(**overrides) -> ChangeEvent:
    base = dict(
        table_schema="dbo",
        table_name="users",
        operation=ChangeOperation.INSERT,
        after_values={"id": 1, "name": "Alice"},
    )
    base.update(overrides)
    return ChangeEvent(**base)


class TestDedupKeyWithLsn:
    def test_lsn_based_key_uses_lsn_string(self) -> None:
        lsn = LsnPosition.from_string("0x00001234:0000ABCD:0001")
        event = _event(lsn=lsn)
        key = DedupKey.for_event(event)
        assert key.value == lsn.to_string()
        assert key.is_synthetic is False

    def test_lsn_key_ignores_row_values(self) -> None:
        """Two events sharing an LSN but differing in payload share a key.

        The LSN is the authoritative change identity when present.
        """
        lsn = LsnPosition.from_string("0x00001234:0000ABCD:0001")
        a = DedupKey.for_event(_event(lsn=lsn, after_values={"id": 1}))
        b = DedupKey.for_event(_event(lsn=lsn, after_values={"id": 2}))
        assert a.value == b.value


class TestDedupKeySynthetic:
    def test_no_lsn_yields_synthetic_key(self) -> None:
        key = DedupKey.for_event(_event())
        assert key.is_synthetic is True
        assert key.value.startswith("syn:")

    def test_synthetic_key_is_stable_for_identical_events(self) -> None:
        """The same logical change must hash identically across reconstructions,
        even though ChangeEvent.event_id is a fresh random UUID each time.
        """
        a = DedupKey.for_event(_event())
        b = DedupKey.for_event(_event())
        assert a.value == b.value

    def test_synthetic_key_independent_of_value_ordering(self) -> None:
        a = DedupKey.for_event(_event(after_values={"id": 1, "name": "Alice"}))
        b = DedupKey.for_event(_event(after_values={"name": "Alice", "id": 1}))
        assert a.value == b.value

    def test_synthetic_key_differs_by_values(self) -> None:
        a = DedupKey.for_event(_event(after_values={"id": 1}))
        b = DedupKey.for_event(_event(after_values={"id": 2}))
        assert a.value != b.value

    def test_synthetic_key_differs_by_operation(self) -> None:
        a = DedupKey.for_event(_event(operation=ChangeOperation.INSERT))
        b = DedupKey.for_event(_event(operation=ChangeOperation.UPDATE))
        assert a.value != b.value

    def test_synthetic_key_differs_by_table(self) -> None:
        a = DedupKey.for_event(_event(table_name="users"))
        b = DedupKey.for_event(_event(table_name="orders"))
        assert a.value != b.value

    def test_delete_uses_before_values(self) -> None:
        """DELETE events carry identity in before_values, not after_values."""
        a = DedupKey.for_event(
            _event(operation=ChangeOperation.DELETE, after_values=None, before_values={"id": 42})
        )
        b = DedupKey.for_event(
            _event(operation=ChangeOperation.DELETE, after_values=None, before_values={"id": 99})
        )
        assert a.value != b.value
        assert a.is_synthetic is True
