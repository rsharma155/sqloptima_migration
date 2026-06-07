"""Repository for durable migration job log lines written by control or data plane.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.metadata_db.models import MigrationJobLogRecord


class MigrationJobLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(
        self,
        job_id: str,
        message: str,
        *,
        level: str = "info",
        logged_at: datetime | None = None,
    ) -> MigrationJobLogRecord:
        record = MigrationJobLogRecord(
            migration_job_id=job_id,
            logged_at=logged_at or datetime.now(UTC),
            level=level,
            message=message,
        )
        self._session.add(record)
        await self._session.commit()
        await self._session.refresh(record)
        return record

    async def list_for_job(self, job_id: str, *, limit: int = 500) -> list[MigrationJobLogRecord]:
        result = await self._session.execute(
            select(MigrationJobLogRecord)
            .where(MigrationJobLogRecord.migration_job_id == job_id)
            .order_by(MigrationJobLogRecord.logged_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())
