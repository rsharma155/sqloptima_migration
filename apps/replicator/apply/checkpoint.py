"""
Module: apps/replicator/apply/checkpoint.py
Purpose: Last-applied-LSN store backed by PostgreSQL metadata table;
         load_all() supports stream resume across restarts.
Author: Migration Platform Team
Created: 2026-05-22
Domain: Replication / Apply
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from apps.replicator.capture.models import LsnPosition

logger = logging.getLogger(__name__)

CHECKPOINT_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS _replication_checkpoint (
    table_schema   TEXT        NOT NULL,
    table_name     TEXT        NOT NULL,
    lsn_bytes      BYTEA       NOT NULL,
    rows_applied   BIGINT      NOT NULL DEFAULT 0,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (table_schema, table_name)
);
"""


@dataclass
class CheckpointEntry:
    """A single checkpoint entry tracking applied position for a table."""

    table_schema: str
    table_name: str
    lsn_bytes: bytes
    rows_applied: int = 0
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def from_lsn(
        cls,
        schema: str,
        table: str,
        lsn: LsnPosition,
        rows: int = 0,
    ) -> CheckpointEntry:
        return cls(
            table_schema=schema,
            table_name=table,
            lsn_bytes=lsn.serialize(),
            rows_applied=rows,
        )


class CheckpointStore:
    """Persists and retrieves replication checkpoints in PostgreSQL.

    Each row stores the last-applied LSN for a (schema, table) pair,
    enabling resume from the exact position after restart.
    """

    def __init__(self, connection: Any) -> None:
        self._conn = connection

    async def ensure_table(self) -> None:
        """Create the checkpoint metadata table if it does not exist."""
        await self._conn.execute(CHECKPOINT_TABLE_DDL)
        logger.info("Replication checkpoint table ensured")

    async def save(
        self,
        schema: str,
        table: str,
        lsn: LsnPosition,
        rows: int = 0,
    ) -> None:
        """Upsert a checkpoint for the given table.

        Args:
            schema: Table schema name.
            table: Table name.
            lsn: Last applied LSN position.
            rows: Total rows applied so far.
        """
        sql = """
        INSERT INTO _replication_checkpoint
            (table_schema, table_name, lsn_bytes, rows_applied, updated_at)
        VALUES ($1, $2, $3, $4, NOW())
        ON CONFLICT (table_schema, table_name)
        DO UPDATE SET lsn_bytes = EXCLUDED.lsn_bytes,
                      rows_applied = _replication_checkpoint.rows_applied + $4,
                      updated_at = NOW();
        """
        await self._conn.execute(sql, schema, table, lsn.serialize(), rows)

    async def load(self, schema: str, table: str) -> CheckpointEntry | None:
        """Load the checkpoint for a given table.

        Args:
            schema: Table schema name.
            table: Table name.

        Returns:
            CheckpointEntry if found, None otherwise.
        """
        sql = """
        SELECT table_schema, table_name, lsn_bytes, rows_applied, updated_at
        FROM _replication_checkpoint
        WHERE table_schema = $1 AND table_name = $2;
        """
        row = await self._conn.fetchrow(sql, schema, table)
        if row is None:
            return None
        return CheckpointEntry(
            table_schema=row["table_schema"],
            table_name=row["table_name"],
            lsn_bytes=bytes(row["lsn_bytes"]),
            rows_applied=row["rows_applied"],
            updated_at=row["updated_at"],
        )

    async def load_all(self, schema: str | None = None) -> list[CheckpointEntry]:
        """Load all checkpoints, optionally filtered by target schema.

        Args:
            schema: When set, only return rows for this ``table_schema``.

        Returns:
            List of CheckpointEntry rows (may be empty).
        """
        if schema is None:
            sql = """
            SELECT table_schema, table_name, lsn_bytes, rows_applied, updated_at
            FROM _replication_checkpoint
            ORDER BY table_schema, table_name;
            """
            rows = await self._conn.fetch(sql)
        else:
            sql = """
            SELECT table_schema, table_name, lsn_bytes, rows_applied, updated_at
            FROM _replication_checkpoint
            WHERE table_schema = $1
            ORDER BY table_name;
            """
            rows = await self._conn.fetch(sql, schema)
        return [
            CheckpointEntry(
                table_schema=row["table_schema"],
                table_name=row["table_name"],
                lsn_bytes=bytes(row["lsn_bytes"]),
                rows_applied=row["rows_applied"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    async def delete(self, schema: str, table: str) -> None:
        """Remove the checkpoint for a given table.

        Args:
            schema: Table schema name.
            table: Table name.
        """
        sql = "DELETE FROM _replication_checkpoint WHERE table_schema = $1 AND table_name = $2;"
        await self._conn.execute(sql, schema, table)
