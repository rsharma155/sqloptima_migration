"""Failure-path / resumability tests (§11.3)."""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from domains.chunking.chunk_planner import ChunkBoundary, ChunkPlan, ChunkStatus
from domains.chunking.chunk_store import ChunkStore
from domains.migration.checkpoint_store import MigrationCheckpointStore
from domains.migration.migration_engine import MigrationCheckpoint, MigrationStatus


@pytest.mark.asyncio
async def test_reset_stale_running_chunks_returns_to_pending():
    mock_conn = AsyncMock()
    mock_conn.execute.return_value = [{"chunk_id": "c1"}, {"chunk_id": "c2"}]
    store = ChunkStore(mock_conn)
    count = await store.reset_stale_running_chunks()
    assert count == 2
    sql = mock_conn.execute.call_args[0][0]
    assert "status = 'pending'" in sql


@pytest.mark.asyncio
async def test_increment_retry_quarantines_after_max_retries():
    mock_conn = AsyncMock()
    mock_conn.execute.return_value = [{"retry_count": 3, "status": "quarantined"}]
    store = ChunkStore(mock_conn)
    retries = await store.increment_retry("chunk-1")
    assert retries == 3


@pytest.mark.asyncio
async def test_checkpoint_resume_preserves_progress(tmp_path):
    db_path = str(tmp_path / "checkpoints.db")
    store = MigrationCheckpointStore(db_path)
    await store.initialize()

    cp = MigrationCheckpoint(
        table_name="orders",
        last_chunk_id=7,
        last_offset=70000,
        total_rows_migrated=70000,
        status=MigrationStatus.RUNNING,
        adapted_chunk_size=5000,
    )
    await store.save_checkpoint(cp)
    loaded = await store.load_checkpoint("orders")
    assert loaded is not None
    assert loaded.last_chunk_id == 7
    assert loaded.adapted_chunk_size == 5000

    cp2 = MigrationCheckpoint(
        table_name="orders",
        last_chunk_id=10,
        last_offset=100000,
        total_rows_migrated=100000,
        status=MigrationStatus.COMPLETED,
        adapted_chunk_size=5000,
    )
    await store.save_checkpoint(cp2)
    resumed = await store.load_checkpoint("orders")
    assert resumed.status == MigrationStatus.COMPLETED


@pytest.mark.asyncio
async def test_get_stale_chunks_detects_expired_lease():
    mock_conn = AsyncMock()
    mock_conn.execute.return_value = [
        {
            "chunk_id": "00000000-0000-0000-0000-000000000001",
            "table_schema": "dbo",
            "table_name": "users",
            "start_boundary": 1,
            "end_boundary": 1000,
            "column_name": "id",
            "status": "running",
            "lease_holder": "worker-a",
            "lease_expires_at": datetime.utcnow() - timedelta(minutes=5),
            "retry_count": 0,
            "max_retries": 3,
            "rows_migrated": 0,
            "error": None,
            "started_at": None,
            "completed_at": None,
        }
    ]
    store = ChunkStore(mock_conn)
    stale = await store.get_stale_chunks()
    assert len(stale) == 1
    assert stale[0].status == ChunkStatus.RUNNING


@pytest.mark.asyncio
async def test_chaos_mid_failure_resume_skips_completed_via_chunk_store(tmp_path):
    """Simulate worker crash mid-table: completed chunks stay done; pending are claimed (§11.3)."""
    from domains.chunking.chunk_planner import ChunkBoundary, ChunkPlan, ChunkStatus as CS

    mock_conn = AsyncMock()
    # First call: reset stale; second: claim returns remaining pending chunk only
    pending = ChunkPlan(
        chunk_id=__import__("uuid").UUID("00000000-0000-0000-0000-000000000002"),
        table_schema="dbo",
        table_name="orders",
        column_name="id",
        boundary=ChunkBoundary(start=1001, end=2000),
        status=CS.PENDING,
    )
    store = ChunkStore(mock_conn)
    mock_conn.execute.return_value = [{"chunk_id": "c-stale"}]
    reset = await store.reset_stale_running_chunks()
    assert reset == 1

    store.claim_chunk = AsyncMock(side_effect=[pending, None])  # type: ignore[method-assign]
    claimed = await store.claim_chunk("worker-b", "dbo", "orders")
    assert claimed is not None
    assert claimed.boundary.start == 1001
    assert await store.claim_chunk("worker-b", "dbo", "orders") is None

    db_path = str(tmp_path / "cp.db")
    cps = MigrationCheckpointStore(db_path)
    await cps.initialize()
    await cps.save_checkpoint(
        MigrationCheckpoint(
            table_name="orders",
            last_chunk_id=1,
            last_offset=1000,
            total_rows_migrated=1000,
            status=MigrationStatus.RUNNING,
            adapted_chunk_size=2500,
        )
    )
    resumed = await cps.load_checkpoint("orders")
    assert resumed is not None
    assert resumed.last_chunk_id == 1
    assert resumed.adapted_chunk_size == 2500
