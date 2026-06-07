"""
Module: domains/migration/checkpoint_store.py
Purpose: SQLite-backed durable checkpoint store for ChunkedMigration.
         Persists MigrationCheckpoint so progress survives process crashes.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import aiosqlite

if TYPE_CHECKING:
    pass

from domains.migration.migration_engine import (
    CHUNK_SIZE_DEFAULT,
    MigrationCheckpoint,
    MigrationStatus,
)
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS migration_checkpoints (
    table_name          TEXT    PRIMARY KEY,
    last_chunk_id       INTEGER NOT NULL DEFAULT 0,
    last_offset         INTEGER NOT NULL DEFAULT 0,
    total_rows_migrated INTEGER NOT NULL DEFAULT 0,
    status              TEXT    NOT NULL DEFAULT 'pending',
    timestamp           TEXT    NOT NULL,
    checkpoint_id       TEXT    NOT NULL,
    adapted_chunk_size  INTEGER NOT NULL DEFAULT 10000
);
"""


class MigrationCheckpointStore:
    """Durable SQLite-backed store for :class:`MigrationCheckpoint` objects.

    Usage::

        store = MigrationCheckpointStore("/var/lib/migration/checkpoints.db")
        await store.initialize()

        cp = await store.load_checkpoint("dbo.orders")
        if cp is None:
            cp = MigrationCheckpoint(table_name="dbo.orders", ...)

        # ...do work...
        cp.last_chunk_id = 5
        await store.save_checkpoint(cp)
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Create the checkpoints table if it does not already exist."""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(_DDL)
            await db.commit()
        logger.info("Migration checkpoint store initialized", db_path=self._db_path)

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    async def save_checkpoint(self, checkpoint: MigrationCheckpoint) -> None:
        """Upsert a checkpoint.  Idempotent — safe to call on every chunk boundary."""
        sql = """
        INSERT INTO migration_checkpoints
            (table_name, last_chunk_id, last_offset, total_rows_migrated,
             status, timestamp, checkpoint_id, adapted_chunk_size)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(table_name) DO UPDATE SET
            last_chunk_id       = excluded.last_chunk_id,
            last_offset         = excluded.last_offset,
            total_rows_migrated = excluded.total_rows_migrated,
            status              = excluded.status,
            timestamp           = excluded.timestamp,
            checkpoint_id       = excluded.checkpoint_id,
            adapted_chunk_size  = excluded.adapted_chunk_size
        """
        adapted = getattr(checkpoint, "adapted_chunk_size", CHUNK_SIZE_DEFAULT)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                sql,
                (
                    checkpoint.table_name,
                    checkpoint.last_chunk_id,
                    checkpoint.last_offset,
                    checkpoint.total_rows_migrated,
                    str(checkpoint.status),
                    checkpoint.timestamp.isoformat(),
                    str(checkpoint.checkpoint_id),
                    adapted,
                ),
            )
            await db.commit()
        logger.debug(
            "Checkpoint saved",
            table=checkpoint.table_name,
            chunk=checkpoint.last_chunk_id,
        )

    async def load_checkpoint(self, table_name: str) -> MigrationCheckpoint | None:
        """Return the checkpoint for *table_name*, or ``None`` if absent."""
        sql = """
        SELECT table_name, last_chunk_id, last_offset, total_rows_migrated,
               status, timestamp, checkpoint_id, adapted_chunk_size
        FROM   migration_checkpoints
        WHERE  table_name = ?
        """
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, (table_name,)) as cursor:
                row = await cursor.fetchone()

        if row is None:
            return None

        from uuid import UUID

        return MigrationCheckpoint(
            table_name=row["table_name"],
            last_chunk_id=row["last_chunk_id"],
            last_offset=row["last_offset"],
            total_rows_migrated=row["total_rows_migrated"],
            status=MigrationStatus(row["status"]),
            timestamp=datetime.fromisoformat(row["timestamp"]).replace(tzinfo=UTC),
            checkpoint_id=UUID(row["checkpoint_id"]),
            adapted_chunk_size=row["adapted_chunk_size"],
        )

    async def delete_checkpoint(self, table_name: str) -> None:
        """Remove the checkpoint for *table_name* (e.g. after a successful full migration)."""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                "DELETE FROM migration_checkpoints WHERE table_name = ?",
                (table_name,),
            )
            await db.commit()
        logger.debug("Checkpoint deleted", table=table_name)

    async def list_checkpoints(self) -> list[MigrationCheckpoint]:
        """Return all stored checkpoints (useful for dashboard / resume-all logic)."""
        sql = """
        SELECT table_name, last_chunk_id, last_offset, total_rows_migrated,
               status, timestamp, checkpoint_id, adapted_chunk_size
        FROM   migration_checkpoints
        ORDER  BY table_name
        """
        from uuid import UUID

        results: list[MigrationCheckpoint] = []
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql) as cursor:
                rows = await cursor.fetchall()

        for row in rows:
            results.append(
                MigrationCheckpoint(
                    table_name=row["table_name"],
                    last_chunk_id=row["last_chunk_id"],
                    last_offset=row["last_offset"],
                    total_rows_migrated=row["total_rows_migrated"],
                    status=MigrationStatus(row["status"]),
                    timestamp=datetime.fromisoformat(row["timestamp"]).replace(tzinfo=UTC),
                    checkpoint_id=UUID(row["checkpoint_id"]),
                    adapted_chunk_size=row["adapted_chunk_size"],
                )
            )
        return results
