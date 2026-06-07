"""
Module: test_chunk_store.py
Purpose: Unit tests
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from domains.chunking.chunk_planner import ChunkBoundary, ChunkPlan, ChunkStatus
from domains.chunking.chunk_store import ChunkStore


@pytest.fixture
def mock_conn():
    conn = AsyncMock()
    return conn


class TestChunkStore:
    @pytest.mark.asyncio
    async def test_ensure_table(self, mock_conn):
        store = ChunkStore(mock_conn)
        await store.ensure_table()
        mock_conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_chunk(self, mock_conn):
        store = ChunkStore(mock_conn)
        chunk = ChunkPlan(
            table_schema="dbo",
            table_name="orders",
            boundary=ChunkBoundary(start=1, end=10000),
            column_name="id",
        )
        await store.save_chunk(chunk)
        assert mock_conn.execute.called

    @pytest.mark.asyncio
    async def test_save_chunks_batch(self, mock_conn):
        store = ChunkStore(mock_conn)
        chunks = [
            ChunkPlan(
                table_schema="dbo",
                table_name="orders",
                boundary=ChunkBoundary(start=1, end=10000),
                column_name="id",
            ),
            ChunkPlan(
                table_schema="dbo",
                table_name="orders",
                boundary=ChunkBoundary(start=10001, end=20000),
                column_name="id",
            ),
        ]
        await store.save_chunks_batch(chunks)
        assert mock_conn.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_update_status_completed(self, mock_conn):
        store = ChunkStore(mock_conn)
        await store.update_status("00000000-0000-0000-0000-000000000003", ChunkStatus.COMPLETED)
        mock_conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_status_running(self, mock_conn):
        store = ChunkStore(mock_conn)
        await store.update_status("00000000-0000-0000-0000-000000000003", ChunkStatus.RUNNING)
        mock_conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_table_summary(self, mock_conn):
        mock_conn.execute.return_value = [
            {
                "total_chunks": 10,
                "completed_chunks": 7,
                "failed_chunks": 2,
                "quarantined_chunks": 1,
                "running_chunks": 0,
                "total_rows_migrated": 50000,
            }
        ]
        store = ChunkStore(mock_conn)
        summary = await store.get_table_summary("dbo", "orders")
        assert summary["total_chunks"] == 10
        assert summary["completed_chunks"] == 7

    @pytest.mark.asyncio
    async def test_increment_retry(self, mock_conn):
        mock_conn.execute.return_value = [{"retry_count": 1, "status": "retrying"}]
        store = ChunkStore(mock_conn)
        count = await store.increment_retry("00000000-0000-0000-0000-000000000003")
        assert count == 1

    @pytest.mark.asyncio
    async def test_get_pending_chunks(self, mock_conn):
        mock_conn.execute.return_value = [
            {
                "chunk_id": "00000000-0000-0000-0000-000000000001",
                "table_schema": "dbo",
                "table_name": "orders",
                "column_name": "id",
                "column_type": "identity_pk",
                "start_boundary": "1",
                "end_boundary": "10000",
                "chunk_hash": "hash1",
                "status": "pending",
                "retry_count": 0,
                "max_retries": 3,
                "fetch_duration_ms": 0.0,
                "rows_migrated": 0,
                "bytes_transferred": 0,
                "error": None,
                "created_at": None,
                "started_at": None,
                "completed_at": None,
                "lease_holder": None,
                "lease_expires_at": None,
            }
        ]
        store = ChunkStore(mock_conn)
        chunks = await store.get_pending_chunks("dbo", "orders")
        assert len(chunks) == 1
        assert chunks[0].table_name == "orders"
        assert chunks[0].boundary.start == 1
        assert chunks[0].boundary.end == 10000
        assert chunks[0].chunk_hash == "hash1"

    @pytest.mark.asyncio
    async def test_delete_chunks_for_table(self, mock_conn):
        store = ChunkStore(mock_conn)
        await store.delete_chunks_for_table("dbo", "orders")
        mock_conn.execute.assert_called_once()


class TestChunkStoreLeasing:
    @pytest.mark.asyncio
    async def test_claim_chunk_returns_chunk(self, mock_conn):
        now = datetime.utcnow()
        mock_conn.execute.return_value = [
            {
                "chunk_id": "00000000-0000-0000-0000-000000000002",
                "table_schema": "dbo",
                "table_name": "orders",
                "column_name": "id",
                "column_type": "identity_pk",
                "start_boundary": "1",
                "end_boundary": "10000",
                "chunk_hash": "hash1",
                "status": "running",
                "retry_count": 0,
                "max_retries": 3,
                "fetch_duration_ms": 0.0,
                "rows_migrated": 0,
                "bytes_transferred": 0,
                "error": None,
                "created_at": now,
                "started_at": now,
                "completed_at": None,
                "lease_holder": "worker-1",
                "lease_expires_at": now + timedelta(seconds=300),
            }
        ]
        store = ChunkStore(mock_conn, lease_duration_seconds=300)
        chunk = await store.claim_chunk("worker-1", "dbo", "orders")
        assert chunk is not None
        assert chunk.chunk_hash == "hash1"
        assert chunk.lease_holder == "worker-1"
        assert chunk.status == ChunkStatus.RUNNING

    @pytest.mark.asyncio
    async def test_claim_chunk_no_available(self, mock_conn):
        mock_conn.execute.return_value = []
        store = ChunkStore(mock_conn)
        chunk = await store.claim_chunk("worker-1", "dbo", "orders")
        assert chunk is None

    @pytest.mark.asyncio
    async def test_release_chunk(self, mock_conn):
        store = ChunkStore(mock_conn)
        await store.release_chunk("00000000-0000-0000-0000-000000000002", "worker-1")
        mock_conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_renew_lease_success(self, mock_conn):
        mock_conn.execute.return_value = [{"chunk_id": "00000000-0000-0000-0000-000000000002"}]
        store = ChunkStore(mock_conn)
        result = await store.renew_lease("00000000-0000-0000-0000-000000000002", "worker-1")
        assert result is True

    @pytest.mark.asyncio
    async def test_renew_lease_failure_wrong_holder(self, mock_conn):
        mock_conn.execute.return_value = []
        store = ChunkStore(mock_conn)
        result = await store.renew_lease("00000000-0000-0000-0000-000000000002", "wrong-worker")
        assert result is False

    @pytest.mark.asyncio
    async def test_expire_stale_leases(self, mock_conn):
        mock_conn.execute.return_value = [{"chunk_id": "00000000-0000-0000-0000-000000000002"}, {"chunk_id": "chunk-2"}]
        store = ChunkStore(mock_conn)
        count = await store.expire_stale_leases()
        assert count == 2

    @pytest.mark.asyncio
    async def test_get_stale_chunks(self, mock_conn):
        mock_conn.execute.return_value = []
        store = ChunkStore(mock_conn)
        chunks = await store.get_stale_chunks()
        assert len(chunks) == 0

    @pytest.mark.asyncio
    async def test_reset_stale_running_chunks(self, mock_conn):
        mock_conn.execute.return_value = [{"chunk_id": "00000000-0000-0000-0000-000000000004"}]
        store = ChunkStore(mock_conn)
        count = await store.reset_stale_running_chunks()
        assert count == 1
