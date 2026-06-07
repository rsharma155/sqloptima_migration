"""Repository for migration_jobs and their child table_plans.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.metadata_db.models import MigrationJobRecord, MigrationTablePlanRecord


class JobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_all(self) -> list[MigrationJobRecord]:
        result = await self._session.execute(
            select(MigrationJobRecord).options(selectinload(MigrationJobRecord.table_plans))
        )
        return list(result.scalars().all())

    async def get_by_id(self, job_id: str) -> MigrationJobRecord | None:
        result = await self._session.execute(
            select(MigrationJobRecord)
            .where(MigrationJobRecord.migration_job_id == job_id)
            .options(selectinload(MigrationJobRecord.table_plans))
        )
        return result.scalar_one_or_none()

    async def upsert(self, record: MigrationJobRecord) -> MigrationJobRecord:
        """Insert or update the job row. Child table_plans are cascaded."""
        record.updated_at = datetime.now(UTC)
        merged = await self._session.merge(record)
        await self._session.commit()
        return merged

    async def update_status(self, job_id: str, status: str) -> None:
        record = await self.get_by_id(job_id)
        if record:
            record.status = status
            record.updated_at = datetime.now(UTC)
            if status in ("COMPLETED", "FAILED", "STOPPED"):
                record.completed_at = datetime.now(UTC)
            await self._session.commit()

    async def update_progress(
        self,
        job_id: str,
        *,
        rows_migrated: int,
        tables_done: int,
    ) -> None:
        record = await self.get_by_id(job_id)
        if record:
            record.rows_migrated = rows_migrated
            record.tables_done = tables_done
            record.updated_at = datetime.now(UTC)
            await self._session.commit()

    async def update_table_plan_status(
        self,
        job_id: str,
        table_name: str,
        status: str,
        rows_migrated: int = 0,
    ) -> None:
        result = await self._session.execute(
            select(MigrationTablePlanRecord).where(
                MigrationTablePlanRecord.migration_job_id == job_id,
                MigrationTablePlanRecord.table_name == table_name,
            )
        )
        plan = result.scalar_one_or_none()
        if plan:
            plan.status = status
            plan.rows_migrated = rows_migrated
            await self._session.commit()
