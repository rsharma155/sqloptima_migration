"""
Module: infrastructure/metadata_db/repositories/validation_repository.py
Purpose: Repository for validation_runs and validation_mismatches tables.
         Persists L1–L4 validation results and individual row/chunk mismatches.
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

from infrastructure.metadata_db.models import (
    ValidationMismatchRecord,
    ValidationRunRecord,
)


class ValidationRepository:
    """Persist and retrieve validation run state and mismatch details.

    One :class:`ValidationRunRecord` is created per validation invocation
    (one per level per job).  Individual mismatches are stored in
    :class:`ValidationMismatchRecord` rows.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Run CRUD
    # ------------------------------------------------------------------

    async def create_run(
        self, job_id: str, level: int
    ) -> ValidationRunRecord:
        """Insert a new PENDING validation run record."""
        run = ValidationRunRecord(
            validation_run_id=str(uuid4()),
            migration_job_id=job_id,
            level=level,
            status="PENDING",
            started_at=None,
            completed_at=None,
            pass_count=0,
            fail_count=0,
            report=None,
        )
        self._session.add(run)
        await self._session.flush()
        return run

    async def start_run(self, run_id: str) -> None:
        """Mark a run as RUNNING and record the start timestamp."""
        run = await self._get_run(run_id)
        if run:
            run.status = "RUNNING"
            run.started_at = datetime.now(UTC)
            await self._session.flush()

    async def complete_run(
        self,
        run_id: str,
        pass_count: int,
        fail_count: int,
        report: dict[str, Any] | None = None,
    ) -> None:
        """Mark a run as COMPLETED with result counts and optional JSON report."""
        run = await self._get_run(run_id)
        if run:
            run.status = "COMPLETED" if fail_count == 0 else "FAILED"
            run.completed_at = datetime.now(UTC)
            run.pass_count = pass_count
            run.fail_count = fail_count
            run.report = report
            await self._session.flush()

    async def fail_run(self, run_id: str, error: str) -> None:
        """Mark a run as ERROR with an error message in the report."""
        run = await self._get_run(run_id)
        if run:
            run.status = "ERROR"
            run.completed_at = datetime.now(UTC)
            run.report = {"error": error}
            await self._session.flush()

    async def get_run(self, run_id: str) -> ValidationRunRecord | None:
        return await self._get_run(run_id)

    async def get_runs_for_job(
        self, job_id: str
    ) -> list[ValidationRunRecord]:
        result = await self._session.execute(
            select(ValidationRunRecord)
            .where(ValidationRunRecord.migration_job_id == job_id)
            .order_by(ValidationRunRecord.level)
        )
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Mismatch CRUD
    # ------------------------------------------------------------------

    async def record_mismatch(
        self,
        run_id: str,
        table_schema: str,
        table_name: str,
        mismatch_type: str,
        source_value: Any,
        target_value: Any,
        details: dict[str, Any] | None = None,
    ) -> ValidationMismatchRecord:
        """Insert a single mismatch row linked to *run_id*."""
        mismatch = ValidationMismatchRecord(
            validation_mismatch_id=str(uuid4()),
            validation_run_id=run_id,
            table_schema=table_schema,
            table_name=table_name,
            mismatch_type=mismatch_type,
            source_value=str(source_value) if source_value is not None else None,
            target_value=str(target_value) if target_value is not None else None,
            details=details,
            created_at=datetime.now(UTC),
        )
        self._session.add(mismatch)
        await self._session.flush()
        return mismatch

    async def bulk_record_mismatches(
        self, run_id: str, mismatches: list[dict[str, Any]]
    ) -> int:
        """Insert multiple mismatch records; returns inserted count."""
        for m in mismatches:
            rec = ValidationMismatchRecord(
                validation_mismatch_id=str(uuid4()),
                validation_run_id=run_id,
                table_schema=m.get("table_schema"),
                table_name=m.get("table_name"),
                mismatch_type=m.get("mismatch_type"),
                source_value=(
                    str(m["source_value"]) if m.get("source_value") is not None else None
                ),
                target_value=(
                    str(m["target_value"]) if m.get("target_value") is not None else None
                ),
                details=m.get("details"),
                created_at=datetime.now(UTC),
            )
            self._session.add(rec)
        await self._session.flush()
        return len(mismatches)

    async def get_mismatches_for_run(
        self, run_id: str
    ) -> list[ValidationMismatchRecord]:
        result = await self._session.execute(
            select(ValidationMismatchRecord)
            .where(ValidationMismatchRecord.validation_run_id == run_id)
            .order_by(ValidationMismatchRecord.created_at)
        )
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _get_run(self, run_id: str) -> ValidationRunRecord | None:
        result = await self._session.execute(
            select(ValidationRunRecord).where(ValidationRunRecord.validation_run_id == run_id)
        )
        return result.scalar_one_or_none()
