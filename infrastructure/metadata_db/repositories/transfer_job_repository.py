"""
Module: transfer_job_repository.py
Purpose: Persistence for transfer_jobs, plans, logs, commands, and settings.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from infrastructure.metadata_db.models import (
    TransferCommandRecord,
    TransferConstraintActionRecord,
    TransferJobLogRecord,
    TransferJobRecord,
    TransferRuntimeSettingsRecord,
    TransferTablePlanRecord,
)


class TransferJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, job_id: str) -> TransferJobRecord | None:
        stmt = (
            select(TransferJobRecord)
            .where(TransferJobRecord.transfer_job_id == job_id)
            .options(
                selectinload(TransferJobRecord.table_plans),
                selectinload(TransferJobRecord.runtime_settings),
            )
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_jobs(self, project_id: str | None = None) -> list[TransferJobRecord]:
        stmt = (
            select(TransferJobRecord)
            .options(selectinload(TransferJobRecord.table_plans))
            .order_by(TransferJobRecord.created_at.desc())
        )
        if project_id:
            stmt = stmt.where(TransferJobRecord.project_id == project_id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def create(
        self,
        *,
        job_id: str | None = None,
        path: str,
        source_connection_id: str,
        target_connection_id: str,
        project_id: str | None,
        tables: list[dict[str, Any]],
        threshold: dict[str, Any],
        constraint_plan: dict[str, Any],
        preflight_json: dict[str, Any] | None,
        config: dict[str, Any] | None,
        rows_total: int = 0,
    ) -> TransferJobRecord:
        job_id = job_id or str(uuid4())
        now = datetime.now(UTC)
        job = TransferJobRecord(
            transfer_job_id=job_id,
            path=path,
            source_project_connection_id=source_connection_id,
            target_project_connection_id=target_connection_id,
            status="queued",
            phase="idle",
            tables_total=len(tables),
            rows_total=rows_total,
            preflight_json=preflight_json,
            constraint_plan=constraint_plan,
            config=config,
            project_id=project_id,
            created_at=now,
            updated_at=now,
        )
        self._session.add(job)
        for table in tables:
            self._session.add(
                TransferTablePlanRecord(
                    transfer_job_id=job_id,
                    source_schema=table["source_schema"],
                    source_table=table["source_table"],
                    target_schema=table["target_schema"],
                    target_table=table["target_table"],
                    chunk_size=int(threshold.get("chunk_size") or 10_000),
                    row_count_estimate=int(table.get("row_count_estimate") or 0),
                    columns=table.get("columns") or [],
                )
            )
        self._session.add(
            TransferRuntimeSettingsRecord(
                transfer_job_id=job_id,
                chunk_size=int(threshold.get("chunk_size") or 10_000),
                min_chunk_size=int(threshold.get("min_chunk_size") or 1_000),
                max_chunk_size=int(threshold.get("max_chunk_size") or 100_000),
                max_rows_per_sec=threshold.get("max_rows_per_sec"),
                updated_at=now,
            )
        )
        await self._session.commit()
        return await self.get(job_id)  # type: ignore[return-value]

    async def add_constraint_actions(self, job_id: str, items: list[dict[str, Any]]) -> None:
        for item in items:
            self._session.add(
                TransferConstraintActionRecord(
                    transfer_job_id=job_id,
                    table_name=f"{item.get('schema')}.{item.get('table')}".strip("."),
                    object_id=str(item["object_id"]),
                    object_kind=str(item["kind"]),
                    planned_action="disable",
                    status="planned",
                )
            )
        if items:
            await self._session.commit()

    async def set_status(
        self,
        job_id: str,
        status: str,
        *,
        phase: str | None = None,
        error: str | None = None,
        set_completed: bool = False,
    ) -> TransferJobRecord | None:
        job = await self.get(job_id)
        if job is None:
            return None
        job.status = status
        if phase is not None:
            job.phase = phase
        if error is not None:
            job.error = error
        if set_completed:
            job.completed_at = datetime.now(UTC)
        job.updated_at = datetime.now(UTC)
        await self._session.commit()
        return job

    async def append_log(
        self,
        job_id: str,
        message: str,
        *,
        level: str = "info",
        phase: str | None = None,
        table_name: str | None = None,
    ) -> None:
        self._session.add(
            TransferJobLogRecord(
                transfer_job_id=job_id,
                message=message,
                level=level,
                phase=phase,
                table_name=table_name,
                logged_at=datetime.now(UTC),
            )
        )
        await self._session.commit()

    async def list_logs(
        self,
        job_id: str,
        *,
        after_id: int = 0,
        limit: int = 200,
        table_name: str | None = None,
    ) -> list[TransferJobLogRecord]:
        stmt = (
            select(TransferJobLogRecord)
            .where(TransferJobLogRecord.transfer_job_id == job_id)
            .where(TransferJobLogRecord.transfer_job_log_id > after_id)
        )
        if table_name:
            stmt = stmt.where(TransferJobLogRecord.table_name == table_name)
        stmt = stmt.order_by(TransferJobLogRecord.transfer_job_log_id.asc()).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def issue_command(self, job_id: str, command: str) -> None:
        record = TransferCommandRecord(
            transfer_job_id=job_id,
            command=command,
            issued_at=datetime.now(UTC),
            acked_at=None,
        )
        await self._session.merge(record)
        await self._session.commit()
        bind = self._session.get_bind()
        if bind.dialect.name == "postgresql":
            from sqlalchemy import text

            await self._session.execute(
                text("SELECT pg_notify('transfer_commands', :job_id)"),
                {"job_id": job_id},
            )
            await self._session.commit()

    async def update_threshold(self, job_id: str, threshold: dict[str, Any]) -> TransferRuntimeSettingsRecord:
        settings = await self._session.get(TransferRuntimeSettingsRecord, job_id)
        now = datetime.now(UTC)
        if settings is None:
            settings = TransferRuntimeSettingsRecord(
                transfer_job_id=job_id,
                updated_at=now,
            )
            self._session.add(settings)
        settings.chunk_size = int(threshold["chunk_size"])
        settings.min_chunk_size = int(threshold["min_chunk_size"])
        settings.max_chunk_size = int(threshold["max_chunk_size"])
        settings.max_rows_per_sec = threshold.get("max_rows_per_sec")
        settings.updated_at = now
        await self._session.commit()
        return settings

    async def find_overlapping(
        self,
        *,
        source_connection_id: str,
        target_connection_id: str,
        target_keys: set[str],
        statuses: set[str],
    ) -> list[TransferJobRecord]:
        stmt = (
            select(TransferJobRecord)
            .options(selectinload(TransferJobRecord.table_plans))
            .where(TransferJobRecord.status.in_(statuses))
            .where(TransferJobRecord.target_project_connection_id == target_connection_id)
        )
        result = await self._session.execute(stmt)
        jobs = []
        for job in result.scalars().all():
            if job.source_project_connection_id != source_connection_id and job.target_project_connection_id != target_connection_id:
                continue
            overlap = []
            for plan in job.table_plans:
                key = f"{plan.target_schema}.{plan.target_table}".lower()
                if key in target_keys:
                    overlap.append(key)
            if overlap:
                jobs.append(job)
        return jobs
