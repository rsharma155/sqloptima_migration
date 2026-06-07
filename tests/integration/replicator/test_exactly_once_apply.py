"""
Module: tests/integration/replicator/test_exactly_once_apply.py
Purpose: End-to-end exactly-once guarantee for the apply path (Issue #4 / #23).
         Drives a realistic stream — duplicated events, and events with AND
         without an LSN — through ChangeApplier + a real Deduplicator, asserting
         each logical change is written exactly once.
Domain: Replication / Apply
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from apps.replicator.apply.applier import ChangeApplier
from apps.replicator.apply.checkpoint import CheckpointStore
from apps.replicator.apply.deduplicator import Deduplicator
from apps.replicator.capture.models import ChangeEvent, ChangeOperation, LsnPosition


@pytest.fixture
def conn():
    c = AsyncMock()
    c.execute = AsyncMock()
    return c


@pytest.fixture
def checkpoint():
    return AsyncMock(spec=CheckpointStore)


@pytest.fixture
def applier(conn, checkpoint):
    # A real (in-memory) Deduplicator so the exactly-once logic is exercised
    # for real, not mocked away.
    return ChangeApplier(connection=conn, checkpoint_store=checkpoint,
                         deduplicator=Deduplicator())


@pytest.mark.asyncio
async def test_stream_with_duplicates_and_missing_lsn_is_exactly_once(
    applier, conn, checkpoint
):
    lsn1 = LsnPosition.from_string("0x00001234:0000ABCD:0001")

    def insert(uid: int, lsn: LsnPosition | None = None) -> ChangeEvent:
        return ChangeEvent(
            table_schema="dbo", table_name="users",
            operation=ChangeOperation.INSERT, after_values={"id": uid},
            lsn=lsn,
        )

    def delete(uid: int) -> ChangeEvent:
        return ChangeEvent(
            table_schema="dbo", table_name="users",
            operation=ChangeOperation.DELETE, before_values={"id": uid},
        )

    stream = [
        insert(1, lsn1),   # LSN-based unique
        insert(1, lsn1),   # exact duplicate (same LSN) -> skipped
        insert(2),         # no LSN -> synthetic identity, unique
        insert(2),         # no LSN, identical content -> skipped
        delete(3),         # no LSN, different op/content -> unique
    ]

    results = [await applier.apply(e) for e in stream]

    assert all(results)  # every apply reports success (incl. skipped duplicates)
    # Three distinct logical changes => exactly three writes to the target.
    assert conn.execute.await_count == 3
    # Checkpoint persists only for the event that carried an authoritative LSN.
    assert checkpoint.save.await_count == 1


@pytest.mark.asyncio
async def test_replay_after_restart_does_not_duplicate(conn, checkpoint):
    """A fresh applier replaying an already-seen LSN-less event must still
    skip it, because dedup identity is derived from content, not object id."""
    lsn_event = ChangeEvent(
        table_schema="dbo", table_name="orders",
        operation=ChangeOperation.INSERT, after_values={"id": 10, "total": 5},
    )

    shared_dedup = Deduplicator()
    first = ChangeApplier(conn, checkpoint, shared_dedup)
    assert await first.apply(lsn_event) is True
    assert conn.execute.await_count == 1

    # Simulate a process restart that keeps the dedup store (e.g. Redis-backed),
    # then re-delivers an identical event.
    second = ChangeApplier(conn, checkpoint, shared_dedup)
    replay = ChangeEvent(
        table_schema="dbo", table_name="orders",
        operation=ChangeOperation.INSERT, after_values={"id": 10, "total": 5},
    )
    assert await second.apply(replay) is True
    assert conn.execute.await_count == 1  # no second write
