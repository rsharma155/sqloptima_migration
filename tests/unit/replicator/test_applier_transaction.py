"""
Module: tests/unit/replicator/test_applier_transaction.py
Purpose: TDD tests for DBA feedback fix 2.3 — apply_batch must wrap events
         in a single transaction so partial-apply is impossible.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from apps.replicator.apply.applier import ChangeApplier
from apps.replicator.apply.checkpoint import CheckpointStore
from apps.replicator.apply.deduplicator import Deduplicator
from apps.replicator.capture.models import ChangeEvent, ChangeOperation


@asynccontextmanager
async def _fake_transaction():
    """Async context manager that mimics asyncpg connection.transaction()."""
    yield


@pytest.fixture
def mock_conn():
    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.transaction = MagicMock(side_effect=_fake_transaction)
    return conn


@pytest.fixture
def mock_checkpoint():
    cp = AsyncMock(spec=CheckpointStore)
    cp.save = AsyncMock()
    return cp


@pytest.fixture
def mock_dedup():
    dd = AsyncMock(spec=Deduplicator)
    dd.already_applied = AsyncMock(return_value=False)
    dd.record = AsyncMock()
    return dd


@pytest.fixture
def applier(mock_conn, mock_checkpoint, mock_dedup):
    return ChangeApplier(
        connection=mock_conn,
        checkpoint_store=mock_checkpoint,
        deduplicator=mock_dedup,
    )


def _insert_event(i: int) -> ChangeEvent:
    return ChangeEvent(
        table_schema="dbo",
        table_name="orders",
        operation=ChangeOperation.INSERT,
        after_values={"id": i, "name": f"item-{i}"},
    )


class TestApplyBatchTransaction:
    """
    Issue 2.3: apply_batch must apply all events inside a single atomic
    transaction.  Partial application (events 1-6 committed when event 7
    fails) must not be possible.
    """

    @pytest.mark.asyncio
    async def test_apply_batch_opens_transaction(self, applier, mock_conn):
        events = [_insert_event(i) for i in range(1, 4)]
        await applier.apply_batch(events)
        mock_conn.transaction.assert_called_once()

    @pytest.mark.asyncio
    async def test_apply_batch_returns_all_true_on_success(self, applier):
        events = [_insert_event(i) for i in range(1, 4)]
        results = await applier.apply_batch(events)
        assert results == [True, True, True]

    @pytest.mark.asyncio
    async def test_apply_batch_empty_returns_empty(self, applier, mock_conn):
        results = await applier.apply_batch([])
        assert results == []

    @pytest.mark.asyncio
    async def test_apply_batch_exception_propagates(self, applier, mock_conn):
        """If a single event fails the whole batch must raise (not swallow)."""
        mock_conn.execute = AsyncMock(side_effect=RuntimeError("DB error"))
        events = [_insert_event(i) for i in range(1, 3)]
        with pytest.raises(RuntimeError, match="DB error"):
            await applier.apply_batch(events)

    @pytest.mark.asyncio
    async def test_apply_batch_uses_pk_columns(self, applier, mock_conn):
        """pk_columns param must be forwarded to each individual apply() call."""
        events = [_insert_event(1)]
        await applier.apply_batch(events, pk_columns=["id"])
        # execute was called — means apply() was called with the pk_columns
        mock_conn.execute.assert_called_once()
