"""
Module: tests/unit/replicator/test_applier.py
Purpose: Unit tests for ChangeApplier — idempotent UPSERT/DELETE/DDL apply
Author: Migration Platform Team
Created: 2026-05-22
Domain: Replication / Apply
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.replicator.apply.applier import ChangeApplier
from apps.replicator.apply.checkpoint import CheckpointStore
from apps.replicator.apply.deduplicator import Deduplicator
from apps.replicator.capture.models import ChangeEvent, ChangeOperation, LsnPosition


from contextlib import asynccontextmanager


@asynccontextmanager
async def _fake_transaction():
    yield


@pytest.fixture
def mock_conn():
    conn = AsyncMock()
    conn.execute = AsyncMock()
    # Fix 2.3: apply_batch now wraps in conn.transaction() — must be an async CM.
    conn.transaction = MagicMock(side_effect=_fake_transaction)
    return conn


@pytest.fixture
def mock_checkpoint():
    cp = AsyncMock(spec=CheckpointStore)
    cp.save = AsyncMock()
    cp.load = AsyncMock(return_value=None)
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


class TestChangeApplier:
    @pytest.mark.asyncio
    async def test_apply_insert(self, applier, mock_conn, mock_dedup, mock_checkpoint):
        event = ChangeEvent(
            table_schema="dbo",
            table_name="users",
            operation=ChangeOperation.INSERT,
            after_values={"id": 1, "name": "Alice", "email": "alice@test.com"},
            lsn=LsnPosition.from_string("0x00001234:0000ABCD:0001"),
        )
        result = await applier.apply(event)
        assert result is True
        
        # Verify that parameters are passed as separate positional arguments, not as a dict.
        # SQL is the first arg, then the values from after_values: 1, "Alice", "alice@test.com"
        call_args = mock_conn.execute.await_args[0]
        assert len(call_args) == 4  # SQL + 3 values
        assert call_args[1] == 1
        assert call_args[2] == "Alice"
        assert call_args[3] == "alice@test.com"
        
        mock_dedup.record.assert_awaited_once()
        mock_checkpoint.save.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_apply_update(self, applier, mock_conn):
        event = ChangeEvent(
            table_schema="dbo",
            table_name="users",
            operation=ChangeOperation.UPDATE,
            after_values={"id": 1, "name": "Bob"},
            lsn=LsnPosition.from_string("0x00001234:0000ABCD:0002"),
        )
        result = await applier.apply(event)
        assert result is True
        
        # SQL + 2 values (id, name)
        call_args = mock_conn.execute.await_args[0]
        assert len(call_args) == 3
        assert call_args[1] == 1
        assert call_args[2] == "Bob"

    @pytest.mark.asyncio
    async def test_apply_delete(self, applier, mock_conn):
        event = ChangeEvent(
            table_schema="dbo",
            table_name="users",
            operation=ChangeOperation.DELETE,
            before_values={"id": 1},
            lsn=LsnPosition.from_string("0x00001234:0000ABCD:0003"),
        )
        result = await applier.apply(event)
        assert result is True
        
        # SQL + 1 value (id)
        call_args = mock_conn.execute.await_args[0]
        assert len(call_args) == 2
        assert call_args[1] == 1

    @pytest.mark.asyncio
    async def test_apply_skips_already_deduplicated(self, applier, mock_dedup, mock_conn):
        mock_dedup.already_applied.return_value = True
        event = ChangeEvent(
            table_schema="dbo", table_name="users",
            operation=ChangeOperation.INSERT, after_values={"id": 1},
            lsn=LsnPosition.from_string("0x00001234:0000ABCD:0001"),
        )
        result = await applier.apply(event)
        assert result is True
        mock_conn.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_apply_without_lsn(self, applier, mock_dedup):
        mock_dedup.already_applied.return_value = False
        event = ChangeEvent(
            table_schema="dbo", table_name="t",
            operation=ChangeOperation.INSERT, after_values={"id": 1},
        )
        result = await applier.apply(event)
        assert result is True

    def test_build_upsert_sql(self, applier):
        event = ChangeEvent(
            table_schema="dbo", table_name="users",
            operation=ChangeOperation.INSERT,
            after_values={"id": 1, "name": "Alice"},
        )
        sql, params = applier._build_upsert(event, ["id"])
        assert "INSERT INTO" in sql or "UPSERT" in sql
        assert "dbo" in sql
        assert "users" in sql
        assert params == {"1": 1, "2": "Alice"}

    def test_build_delete_sql(self, applier):
        event = ChangeEvent(
            table_schema="dbo", table_name="users",
            operation=ChangeOperation.DELETE,
            before_values={"id": 42},
        )
        sql, params = applier._build_delete(event, ["id"])
        assert "DELETE FROM" in sql
        assert "id" in sql
        assert params == {"1": 42}

    @pytest.mark.asyncio
    async def test_apply_without_lsn_is_idempotent(self, mock_conn, mock_checkpoint):
        """An event with no LSN must still be deduplicated exactly-once via the
        synthetic content-based key (Issue #4)."""
        real_dedup = Deduplicator()
        applier = ChangeApplier(
            connection=mock_conn,
            checkpoint_store=mock_checkpoint,
            deduplicator=real_dedup,
        )

        def make_event() -> ChangeEvent:
            return ChangeEvent(
                table_schema="dbo", table_name="t",
                operation=ChangeOperation.INSERT, after_values={"id": 7},
            )

        assert await applier.apply(make_event()) is True
        assert await applier.apply(make_event()) is True
        # Second apply is a duplicate (same content, no LSN) → not re-executed.
        assert mock_conn.execute.await_count == 1

    @pytest.mark.asyncio
    async def test_apply_batch(self, applier, mock_conn):
        events = [
            ChangeEvent(
                table_schema="dbo", table_name="users",
                operation=ChangeOperation.INSERT, after_values={"id": i},
            )
            for i in range(5)
        ]
        results = await applier.apply_batch(events)
        assert len(results) == 5
        assert all(results)

    @pytest.mark.asyncio
    async def test_apply_batch_empty(self, applier):
        results = await applier.apply_batch([])
        assert results == []
