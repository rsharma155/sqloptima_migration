"""
Module: tests/unit/test_migration_checkpoint_store.py
Purpose: TDD tests for MigrationCheckpointStore — SQLite-backed checkpoint persistence
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import pytest

from domains.migration.checkpoint_store import MigrationCheckpointStore
from domains.migration.migration_engine import (
    CHUNK_SIZE_DEFAULT,
    MigrationCheckpoint,
    MigrationStatus,
)


@pytest.fixture
async def store(tmp_path):
    """Return an in-memory SQLite checkpoint store."""
    db_path = str(tmp_path / "checkpoints.db")
    s = MigrationCheckpointStore(db_path)
    await s.initialize()
    return s


class TestMigrationCheckpointStoreBasics:
    async def test_load_missing_returns_none(self, store):
        result = await store.load_checkpoint("dbo.orders")
        assert result is None

    async def test_save_and_load_roundtrip(self, store):
        cp = MigrationCheckpoint(
            table_name="dbo.users",
            last_chunk_id=5,
            last_offset=50000,
            total_rows_migrated=50000,
            status=MigrationStatus.RUNNING,
        )
        await store.save_checkpoint(cp)
        loaded = await store.load_checkpoint("dbo.users")
        assert loaded is not None
        assert loaded.table_name == "dbo.users"
        assert loaded.last_chunk_id == 5
        assert loaded.last_offset == 50000
        assert loaded.total_rows_migrated == 50000
        assert loaded.status == MigrationStatus.RUNNING

    async def test_save_overwrites_existing(self, store):
        cp1 = MigrationCheckpoint(
            table_name="dbo.orders",
            last_chunk_id=1,
            last_offset=1000,
            total_rows_migrated=1000,
            status=MigrationStatus.RUNNING,
        )
        await store.save_checkpoint(cp1)

        cp2 = MigrationCheckpoint(
            table_name="dbo.orders",
            last_chunk_id=3,
            last_offset=3000,
            total_rows_migrated=3000,
            status=MigrationStatus.COMPLETED,
        )
        await store.save_checkpoint(cp2)

        loaded = await store.load_checkpoint("dbo.orders")
        assert loaded is not None
        assert loaded.last_chunk_id == 3
        assert loaded.total_rows_migrated == 3000
        assert loaded.status == MigrationStatus.COMPLETED

    async def test_delete_checkpoint(self, store):
        cp = MigrationCheckpoint(
            table_name="dbo.products",
            last_chunk_id=2,
            last_offset=2000,
            total_rows_migrated=2000,
            status=MigrationStatus.COMPLETED,
        )
        await store.save_checkpoint(cp)
        await store.delete_checkpoint("dbo.products")
        result = await store.load_checkpoint("dbo.products")
        assert result is None

    async def test_list_all_checkpoints(self, store):
        for name in ("dbo.a", "dbo.b", "dbo.c"):
            cp = MigrationCheckpoint(
                table_name=name,
                last_chunk_id=0,
                last_offset=0,
                total_rows_migrated=0,
                status=MigrationStatus.PENDING,
            )
            await store.save_checkpoint(cp)

        all_cps = await store.list_checkpoints()
        names = {c.table_name for c in all_cps}
        assert {"dbo.a", "dbo.b", "dbo.c"} == names

    async def test_checkpoint_id_is_preserved(self, store):
        cp = MigrationCheckpoint(
            table_name="dbo.logs",
            last_chunk_id=0,
            last_offset=0,
            total_rows_migrated=0,
            status=MigrationStatus.PENDING,
        )
        await store.save_checkpoint(cp)
        loaded = await store.load_checkpoint("dbo.logs")
        assert str(loaded.checkpoint_id) == str(cp.checkpoint_id)

    async def test_timestamp_is_preserved(self, store):
        from datetime import UTC, datetime
        cp = MigrationCheckpoint(
            table_name="dbo.events",
            last_chunk_id=0,
            last_offset=0,
            total_rows_migrated=0,
            status=MigrationStatus.PENDING,
        )
        await store.save_checkpoint(cp)
        loaded = await store.load_checkpoint("dbo.events")
        # Timestamp should round-trip within 1 second
        delta = abs((loaded.timestamp - cp.timestamp).total_seconds())
        assert delta < 1.0


class TestMigrationCheckpointStorePersistence:
    """Verify data survives store re-open (simulating process restart)."""

    async def test_survives_reopen(self, tmp_path):
        db_path = str(tmp_path / "persist.db")

        store1 = MigrationCheckpointStore(db_path)
        await store1.initialize()
        cp = MigrationCheckpoint(
            table_name="dbo.heavy",
            last_chunk_id=42,
            last_offset=420000,
            total_rows_migrated=420000,
            status=MigrationStatus.RUNNING,
        )
        await store1.save_checkpoint(cp)

        # Simulate restart: create a new store instance pointing at the same file
        store2 = MigrationCheckpointStore(db_path)
        await store2.initialize()
        loaded = await store2.load_checkpoint("dbo.heavy")
        assert loaded is not None
        assert loaded.last_chunk_id == 42
        assert loaded.total_rows_migrated == 420000


class TestAdaptedChunkSizePersistence:
    """1.7: adapted_chunk_size field survives save/load."""

    async def test_adapted_chunk_size_defaults(self, store):
        cp = MigrationCheckpoint(
            table_name="dbo.big",
            last_chunk_id=0,
            last_offset=0,
            total_rows_migrated=0,
            status=MigrationStatus.PENDING,
        )
        assert cp.adapted_chunk_size == CHUNK_SIZE_DEFAULT

    async def test_adapted_chunk_size_roundtrip(self, store):
        cp = MigrationCheckpoint(
            table_name="dbo.big",
            last_chunk_id=10,
            last_offset=100000,
            total_rows_migrated=100000,
            status=MigrationStatus.RUNNING,
            adapted_chunk_size=25000,
        )
        await store.save_checkpoint(cp)
        loaded = await store.load_checkpoint("dbo.big")
        assert loaded.adapted_chunk_size == 25000
