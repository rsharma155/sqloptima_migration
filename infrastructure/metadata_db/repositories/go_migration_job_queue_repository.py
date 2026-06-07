"""Repository for queued migration jobs consumed by the Go data plane.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from infrastructure.metadata_db.models import MigrationJobRecord


class GoMigrationJobQueueRepository:
    """Read and claim jobs dispatched to the Go migration-engine."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_queued_go_jobs(self, *, limit: int = 10) -> list[MigrationJobRecord]:
        result = await self._session.execute(
            select(MigrationJobRecord)
            .where(
                MigrationJobRecord.executor == "go",
                MigrationJobRecord.status == "queued",
            )
            .options(selectinload(MigrationJobRecord.table_plans))
            .order_by(MigrationJobRecord.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def claim_job(self, job_id: str) -> bool:
        """Atomically move a queued job to running. Returns False if not queued."""
        stmt = (
            update(MigrationJobRecord)
            .where(
                MigrationJobRecord.migration_job_id == job_id,
                MigrationJobRecord.status == "queued",
            )
            .values(status="running", started_at=datetime.now(UTC), updated_at=datetime.now(UTC))
        )
        result = await self._session.execute(stmt)
        await self._session.commit()
        return result.rowcount > 0

    async def save_dispatch_config(self, job_id: str, config: dict) -> None:
        record = await self._session.get(MigrationJobRecord, job_id)
        if record is None:
            raise KeyError(job_id)
        record.config = config
        record.executor = "go"
        record.status = "queued"
        record.updated_at = datetime.now(UTC)
        await self._session.commit()
