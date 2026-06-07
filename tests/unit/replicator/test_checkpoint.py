"""
Module: tests/unit/replicator/test_checkpoint.py
Purpose: Unit tests for CheckpointStore (PostgreSQL metadata table)
Author: Migration Platform Team
Created: 2026-05-22
Domain: Replication / Apply
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from apps.replicator.apply.checkpoint import CheckpointEntry, CheckpointStore
from apps.replicator.capture.models import LsnPosition


@pytest.fixture
def mock_conn():
    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.fetchrow = AsyncMock()
    return conn


class TestCheckpointEntry:
    def test_create_entry(self):
        lsn = LsnPosition.from_string("0x00001234:0000ABCD:0001")
        entry = CheckpointEntry(
            table_schema="dbo",
            table_name="users",
            lsn_bytes=lsn.serialize(),
        )
        assert entry.table_schema == "dbo"
        assert entry.lsn_bytes == lsn.serialize()
        assert entry.rows_applied == 0

    def test_entry_from_lsn(self):
        lsn = LsnPosition.from_string("0x00001234:0000ABCD:0001")
        entry = CheckpointEntry.from_lsn("sales", "orders", lsn, rows=100)
        assert entry.lsn_bytes == lsn.serialize()
        assert entry.rows_applied == 100


class TestCheckpointStore:
    @pytest.mark.asyncio
    async def test_save_checkpoint(self, mock_conn):
        store = CheckpointStore(mock_conn)
        lsn = LsnPosition.from_string("0x00001234:0000ABCD:0001")
        await store.save("dbo", "users", lsn, rows=50)
        mock_conn.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_load_checkpoint_returns_none_when_empty(self, mock_conn):
        mock_conn.fetchrow = AsyncMock(return_value=None)
        store = CheckpointStore(mock_conn)
        result = await store.load("dbo", "nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_load_checkpoint_returns_entry(self, mock_conn):
        lsn = LsnPosition.from_string("0x00001234:0000ABCD:0001")
        mock_conn.fetchrow = AsyncMock(
            return_value={
                "table_schema": "dbo",
                "table_name": "users",
                "lsn_bytes": lsn.serialize(),
                "rows_applied": 100,
                "updated_at": datetime(2026, 5, 22, tzinfo=UTC),
            }
        )
        store = CheckpointStore(mock_conn)
        entry = await store.load("dbo", "users")
        assert entry is not None
        assert entry.table_name == "users"
        assert entry.rows_applied == 100
        assert entry.lsn_bytes == lsn.serialize()

    @pytest.mark.asyncio
    async def test_ensure_table_creates_metadata(self, mock_conn):
        store = CheckpointStore(mock_conn)
        await store.ensure_table()
        mock_conn.execute.assert_awaited_once()
        sql = mock_conn.execute.call_args[0][0]
        assert "CREATE TABLE IF NOT EXISTS" in sql
        assert "_replication_checkpoint" in sql

    @pytest.mark.asyncio
    async def test_delete_checkpoint(self, mock_conn):
        store = CheckpointStore(mock_conn)
        await store.delete("dbo", "users")
        mock_conn.execute.assert_awaited_once()
        sql = mock_conn.execute.call_args[0][0]
        assert "DELETE FROM" in sql
