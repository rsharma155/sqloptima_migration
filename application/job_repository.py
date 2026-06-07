"""
Module: application/job_repository.py
Purpose: SQLite-backed persistent store for MigrationJob objects.
         Fix 7.1: provides crash-resistant job persistence so in-flight job state
         survives process restarts — filling the gap left by the purely in-memory
         JobRegistry which loses all jobs on restart.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import aiosqlite

from domains.migration.migration_engine import (
    MigrationJob,
    MigrationStatus,
    MigrationStrategy,
    TableMigrationPlan,
)
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)

_CREATE_JOBS_TABLE = """
CREATE TABLE IF NOT EXISTS migration_jobs (
    job_id       TEXT PRIMARY KEY,
    status       TEXT NOT NULL,
    error_msg    TEXT,
    source_conn  TEXT NOT NULL,
    target_conn  TEXT NOT NULL,
    tables_json  TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
)
"""


class JobRepository:
    """SQLite-backed persistent store for MigrationJob.

    Supports aiosqlite for non-blocking I/O.  Pass ``db_path=":memory:"``
    in tests for an in-memory database that is automatically discarded.
    """

    def __init__(self, db_path: str = "migration_jobs.db") -> None:
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Open the database and create tables if absent."""
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute(_CREATE_JOBS_TABLE)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def create(self, job: MigrationJob) -> None:
        """Persist a new MigrationJob."""
        await self._ensure_open()
        tables_json = json.dumps([
            {
                "table_name": t.table_name,
                "schema_name": t.schema_name,
                "columns": t.columns,
                "row_count_estimate": t.row_count_estimate,
                "strategy": str(t.strategy),
            }
            for t in job.tables
        ])
        await self._db.execute(
            """
            INSERT OR REPLACE INTO migration_jobs
              (job_id, status, error_msg, source_conn, target_conn,
               tables_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(job.job_id),
                str(job.status),
                job.error_message,
                str(job.source_connection_id),
                str(job.target_connection_id),
                tables_json,
                job.created_at.isoformat(),
                job.updated_at.isoformat(),
            ),
        )
        await self._db.commit()

    async def get(self, job_id: str) -> MigrationJob | None:
        """Load a job by its ID. Returns None if not found."""
        await self._ensure_open()
        async with self._db.execute(
            "SELECT * FROM migration_jobs WHERE job_id = ?", (job_id,)
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_job(dict(row))

    async def list_all(self) -> list[MigrationJob]:
        """Return all persisted jobs ordered by creation time."""
        await self._ensure_open()
        async with self._db.execute(
            "SELECT * FROM migration_jobs ORDER BY created_at"
        ) as cursor:
            rows = await cursor.fetchall()
        return [self._row_to_job(dict(r)) for r in rows]

    async def update_status(
        self,
        job_id: str,
        status: MigrationStatus,
        error: str | None = None,
    ) -> None:
        """Update job status (and optionally error message)."""
        await self._ensure_open()
        await self._db.execute(
            """
            UPDATE migration_jobs
               SET status = ?, error_msg = ?, updated_at = ?
             WHERE job_id = ?
            """,
            (str(status), error, datetime.now(UTC).isoformat(), job_id),
        )
        await self._db.commit()

    async def delete(self, job_id: str) -> None:
        """Delete a job record. Silently succeeds if the job doesn't exist."""
        await self._ensure_open()
        await self._db.execute(
            "DELETE FROM migration_jobs WHERE job_id = ?", (job_id,)
        )
        await self._db.commit()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _ensure_open(self) -> None:
        if self._db is None:
            raise RuntimeError("JobRepository not initialized. Call initialize() first.")

    @staticmethod
    def _row_to_job(row: dict[str, Any]) -> MigrationJob:
        tables_data: list[dict] = json.loads(row["tables_json"])
        tables = [
            TableMigrationPlan(
                table_name=t["table_name"],
                schema_name=t["schema_name"],
                columns=t["columns"],
                row_count_estimate=t.get("row_count_estimate", 0),
                strategy=MigrationStrategy(t.get("strategy", "chunked")),
            )
            for t in tables_data
        ]
        job = MigrationJob(
            source_connection_id=UUID(row["source_conn"]),
            target_connection_id=UUID(row["target_conn"]),
            tables=tables,
            status=MigrationStatus(row["status"]),
        )
        job.job_id = UUID(row["job_id"])
        job.error_message = row.get("error_msg")
        job.created_at = datetime.fromisoformat(row["created_at"])
        job.updated_at = datetime.fromisoformat(row["updated_at"])
        return job
