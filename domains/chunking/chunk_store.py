"""
Module: chunk_store.py
Purpose: Data chunking for bulk migrations
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from domains.chunking.chunk_planner import ChunkPlan, ChunkStatus
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)

LEASE_DURATION_SECONDS = 300


CHUNK_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS _migration_chunks (
    chunk_id            UUID        PRIMARY KEY,
    table_schema        TEXT        NOT NULL,
    table_name          TEXT        NOT NULL,
    column_name         TEXT        NOT NULL,
    column_type         TEXT        NOT NULL,
    start_boundary      TEXT        NOT NULL,
    end_boundary        TEXT        NOT NULL,
    chunk_hash          TEXT        NOT NULL UNIQUE,
    status              TEXT        NOT NULL DEFAULT 'pending',
    retry_count         INT         NOT NULL DEFAULT 0,
    max_retries         INT         NOT NULL DEFAULT 3,
    fetch_duration_ms   REAL        NOT NULL DEFAULT 0,
    rows_migrated       BIGINT      NOT NULL DEFAULT 0,
    bytes_transferred   BIGINT      NOT NULL DEFAULT 0,
    error               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    lease_holder        TEXT,
    lease_expires_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_chunks_status ON _migration_chunks(status);
CREATE INDEX IF NOT EXISTS idx_chunks_table ON _migration_chunks(table_schema, table_name);
CREATE INDEX IF NOT EXISTS idx_chunks_lease ON _migration_chunks(lease_holder, lease_expires_at);
"""


class ChunkStore:
    def __init__(self, connection: Any, lease_duration_seconds: int = LEASE_DURATION_SECONDS):
        self._conn = connection
        self._lease_duration = lease_duration_seconds

    async def ensure_table(self) -> None:
        await self._conn.execute(CHUNK_TABLE_DDL)
        logger.info("Migration chunks table ensured")

    async def save_chunk(self, chunk: ChunkPlan) -> None:
        sql = """
        INSERT INTO _migration_chunks (
            chunk_id, table_schema, table_name, column_name, column_type,
            start_boundary, end_boundary, chunk_hash, status,
            retry_count, max_retries, fetch_duration_ms,
            rows_migrated, bytes_transferred, error,
            created_at, started_at, completed_at,
            lease_holder, lease_expires_at
        ) VALUES (
            $1, $2, $3, $4, $5,
            $6, $7, $8, $9,
            $10, $11, $12,
            $13, $14, $15,
            $16, $17, $18,
            $19, $20
        )
        ON CONFLICT (chunk_id) DO UPDATE SET
            status = EXCLUDED.status,
            retry_count = EXCLUDED.retry_count,
            fetch_duration_ms = EXCLUDED.fetch_duration_ms,
            rows_migrated = EXCLUDED.rows_migrated,
            bytes_transferred = EXCLUDED.bytes_transferred,
            error = EXCLUDED.error,
            started_at = EXCLUDED.started_at,
            completed_at = EXCLUDED.completed_at,
            lease_holder = EXCLUDED.lease_holder,
            lease_expires_at = EXCLUDED.lease_expires_at;
        """
        await self._conn.execute(sql,
            str(chunk.chunk_id),
            chunk.table_schema,
            chunk.table_name,
            chunk.column_name,
            chunk.column_type.value,
            str(chunk.boundary.start) if chunk.boundary else "",
            str(chunk.boundary.end) if chunk.boundary else "",
            chunk.chunk_hash,
            chunk.status.value,
            chunk.retry_count,
            chunk.max_retries,
            chunk.fetch_duration_ms,
            chunk.rows_migrated,
            chunk.bytes_transferred,
            chunk.error,
            chunk.created_at,
            chunk.started_at,
            chunk.completed_at,
            chunk.lease_holder,
            chunk.lease_expires_at,
        )

    async def save_chunks_batch(self, chunks: list[ChunkPlan]) -> None:
        for chunk in chunks:
            await self.save_chunk(chunk)

    async def claim_chunk(
        self, worker_id: str, schema: str, table: str
    ) -> ChunkPlan | None:
        now = datetime.utcnow()
        sql = """
        UPDATE _migration_chunks
        SET status = 'running',
            started_at = $1,
            lease_holder = $2,
            lease_expires_at = $3,
            retry_count = CASE
                WHEN status = 'retrying' THEN retry_count + 1
                ELSE retry_count
            END
        WHERE chunk_id = (
            SELECT chunk_id FROM _migration_chunks
            WHERE table_schema = $4
              AND table_name = $5
              AND (
                  status IN ('pending', 'failed', 'retrying')
                  OR (status = 'running' AND lease_expires_at < $1)
              )
            ORDER BY start_boundary ASC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        )
        RETURNING *
        """
        expires_at = now + timedelta(seconds=self._lease_duration)
        rows = await self._conn.execute(sql, now, worker_id, expires_at, schema, table)
        if not rows:
            return None
        return self._row_to_chunk(rows[0])

    async def release_chunk(
        self, chunk_id: str, worker_id: str
    ) -> None:
        sql = """
        UPDATE _migration_chunks
        SET lease_holder = NULL,
            lease_expires_at = NULL
        WHERE chunk_id = $1 AND lease_holder = $2
        """
        await self._conn.execute(sql, chunk_id, worker_id)

    async def renew_lease(self, chunk_id: str, worker_id: str) -> bool:
        now = datetime.utcnow()
        expires_at = now + timedelta(seconds=self._lease_duration)
        sql = """
        UPDATE _migration_chunks
        SET lease_expires_at = $1
        WHERE chunk_id = $2 AND lease_holder = $3
        RETURNING chunk_id
        """
        rows = await self._conn.execute(sql, expires_at, chunk_id, worker_id)
        return len(rows) > 0

    async def expire_stale_leases(self) -> int:
        now = datetime.utcnow()
        sql = """
        UPDATE _migration_chunks
        SET status = 'pending',
            lease_holder = NULL,
            lease_expires_at = NULL
        WHERE status = 'running'
          AND lease_expires_at < $1
        RETURNING chunk_id
        """
        rows = await self._conn.execute(sql, now)
        count = len(rows)
        if count > 0:
            logger.info("Expired stale leases", count=count)
        return count

    async def get_pending_chunks(
        self, schema: str, table: str
    ) -> list[ChunkPlan]:
        sql = """
        SELECT * FROM _migration_chunks
        WHERE table_schema = $1
          AND table_name = $2
          AND status IN ('pending', 'failed', 'retrying')
        ORDER BY start_boundary ASC
        """
        rows = await self._conn.execute(sql, schema, table)
        return [self._row_to_chunk(r) for r in rows]

    async def get_incomplete_chunks(
        self, schema: str, table: str
    ) -> list[ChunkPlan]:
        sql = """
        SELECT * FROM _migration_chunks
        WHERE table_schema = $1
          AND table_name = $2
          AND status != 'completed'
        ORDER BY start_boundary ASC
        """
        rows = await self._conn.execute(sql, schema, table)
        return [self._row_to_chunk(r) for r in rows]

    async def get_stale_chunks(self) -> list[ChunkPlan]:
        now = datetime.utcnow()
        sql = """
        SELECT * FROM _migration_chunks
        WHERE status = 'running'
          AND lease_expires_at < $1
        ORDER BY start_boundary ASC
        """
        rows = await self._conn.execute(sql, now)
        return [self._row_to_chunk(r) for r in rows]

    async def update_status(
        self, chunk_id: str, status: ChunkStatus, error: str | None = None
    ) -> None:
        now = datetime.utcnow()
        if status == ChunkStatus.RUNNING:
            sql = "UPDATE _migration_chunks SET status = $1, started_at = $2 WHERE chunk_id = $3"
            await self._conn.execute(sql, status.value, now, chunk_id)
        elif status in (ChunkStatus.COMPLETED, ChunkStatus.FAILED, ChunkStatus.QUARANTINED):
            sql = "UPDATE _migration_chunks SET status = $1, completed_at = $2, error = $3, lease_holder = NULL, lease_expires_at = NULL WHERE chunk_id = $4"
            await self._conn.execute(sql, status.value, now, error, chunk_id)
        else:
            sql = "UPDATE _migration_chunks SET status = $1 WHERE chunk_id = $2"
            await self._conn.execute(sql, status.value, chunk_id)

    async def increment_retry(self, chunk_id: str) -> int:
        sql = """
        UPDATE _migration_chunks
        SET retry_count = retry_count + 1,
            status = CASE
                WHEN retry_count + 1 >= max_retries THEN 'quarantined'
                ELSE 'retrying'
            END,
            lease_holder = NULL,
            lease_expires_at = NULL
        WHERE chunk_id = $1
        RETURNING retry_count, status
        """
        row = await self._conn.execute(sql, chunk_id)
        if row:
            return row[0].get("retry_count", 0)
        return 0

    async def get_table_summary(
        self, schema: str, table: str
    ) -> dict[str, Any]:
        sql = """
        SELECT
            COUNT(*) AS total_chunks,
            COUNT(*) FILTER (WHERE status = 'completed') AS completed_chunks,
            COUNT(*) FILTER (WHERE status = 'failed') AS failed_chunks,
            COUNT(*) FILTER (WHERE status = 'quarantined') AS quarantined_chunks,
            COUNT(*) FILTER (WHERE status = 'running') AS running_chunks,
            COALESCE(SUM(rows_migrated), 0) AS total_rows_migrated
        FROM _migration_chunks
        WHERE table_schema = $1 AND table_name = $2
        """
        rows = await self._conn.execute(sql, schema, table)
        return rows[0] if rows else {}

    async def delete_chunks_for_table(self, schema: str, table: str) -> None:
        sql = "DELETE FROM _migration_chunks WHERE table_schema = $1 AND table_name = $2"
        await self._conn.execute(sql, schema, table)

    async def reset_stale_running_chunks(self) -> int:
        now = datetime.utcnow()
        sql = """
        UPDATE _migration_chunks
        SET status = 'pending',
            lease_holder = NULL,
            lease_expires_at = NULL,
            started_at = NULL
        WHERE status = 'running'
          AND (lease_holder IS NULL OR lease_expires_at < $1)
        RETURNING chunk_id
        """
        rows = await self._conn.execute(sql, now)
        count = len(rows)
        if count > 0:
            logger.info("Reset stale running chunks to pending", count=count)
        return count

    def _row_to_chunk(self, row: dict) -> ChunkPlan:
        from domains.chunking.chunk_planner import ChunkBoundary, ChunkColumnType
        return ChunkPlan(
            chunk_id=UUID(row["chunk_id"]) if isinstance(row["chunk_id"], str) else row["chunk_id"],
            table_schema=row.get("table_schema", ""),
            table_name=row.get("table_name", ""),
            boundary=ChunkBoundary(
                start=self._parse_boundary(row.get("start_boundary", "")),
                end=self._parse_boundary(row.get("end_boundary", "")),
            ),
            column_name=row.get("column_name", ""),
            column_type=ChunkColumnType(row.get("column_type", "identity_pk")),
            status=ChunkStatus(row.get("status", "pending")),
            retry_count=row.get("retry_count", 0),
            max_retries=row.get("max_retries", 3),
            chunk_hash=row.get("chunk_hash", ""),
            fetch_duration_ms=row.get("fetch_duration_ms", 0.0),
            rows_migrated=row.get("rows_migrated", 0),
            bytes_transferred=row.get("bytes_transferred", 0),
            error=row.get("error"),
            created_at=row.get("created_at", datetime.utcnow()),
            started_at=row.get("started_at"),
            completed_at=row.get("completed_at"),
            lease_holder=row.get("lease_holder"),
            lease_expires_at=row.get("lease_expires_at"),
        )

    @staticmethod
    def _parse_boundary(value: str) -> Any:
        if not value:
            return None
        try:
            return int(value)
        except ValueError:
            pass
        try:
            return float(value)
        except ValueError:
            pass
        return value
