"""
Module: infrastructure/metadata_db/repositories/chunk_repository.py
Purpose: Repository for migration_table_plans rows (chunk-level state tracking).
         Provides atomic claim, status update, and progress queries used by
         the migration worker.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.metadata_db.models import MigrationTablePlanRecord


class ChunkRepository:
    """CRUD and status-transition operations for migration table plans.

    A *table plan* is the unit of work the migration worker claims and
    processes.  The repository enforces the valid status transitions::

        pending → running → completed | failed | stopped
    """

    _VALID_TRANSITIONS: dict[str, set[str]] = {
        "pending": {"running"},
        "running": {"completed", "failed", "stopped"},
        "failed": {"pending"},   # retry
        "stopped": {"pending"},  # restart
        "completed": set(),
    }

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def get_by_job(self, job_id: str) -> list[MigrationTablePlanRecord]:
        """Return all table plans for *job_id*, ordered by id."""
        result = await self._session.execute(
            select(MigrationTablePlanRecord)
            .where(MigrationTablePlanRecord.migration_job_id == job_id)
            .order_by(MigrationTablePlanRecord.migration_table_plan_id)
        )
        return list(result.scalars().all())

    async def get_pending(self, job_id: str) -> list[MigrationTablePlanRecord]:
        """Return all *pending* table plans for *job_id*."""
        result = await self._session.execute(
            select(MigrationTablePlanRecord)
            .where(
                MigrationTablePlanRecord.migration_job_id == job_id,
                MigrationTablePlanRecord.status == "pending",
            )
            .order_by(MigrationTablePlanRecord.migration_table_plan_id)
        )
        return list(result.scalars().all())

    async def get_by_id(self, plan_id: int) -> MigrationTablePlanRecord | None:
        result = await self._session.execute(
            select(MigrationTablePlanRecord).where(
                MigrationTablePlanRecord.migration_table_plan_id == plan_id
            )
        )
        return result.scalar_one_or_none()

    async def get_progress(self, job_id: str) -> dict[str, Any]:
        """Return aggregate progress stats for *job_id*."""
        plans = await self.get_by_job(job_id)
        total = len(plans)
        counts: dict[str, int] = {}
        rows_done = 0
        rows_total = 0
        for p in plans:
            counts[p.status] = counts.get(p.status, 0) + 1
            rows_done += p.rows_migrated or 0
            rows_total += p.row_count_estimate or 0
        return {
            "total_plans": total,
            "status_counts": counts,
            "rows_migrated": rows_done,
            "rows_total": rows_total,
            "pct_complete": round(rows_done / rows_total * 100, 1) if rows_total else 0.0,
        }

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    async def create_plan(
        self,
        job_id: str,
        table_name: str,
        schema_name: str = "dbo",
        strategy: str = "chunked",
        chunk_size: int = 10_000,
        parallel_workers: int = 4,
        row_count_estimate: int = 0,
    ) -> MigrationTablePlanRecord:
        """Insert a new pending table plan."""
        plan = MigrationTablePlanRecord(
            migration_job_id=job_id,
            table_name=table_name,
            schema_name=schema_name,
            strategy=strategy,
            chunk_size=chunk_size,
            parallel_workers=parallel_workers,
            row_count_estimate=row_count_estimate,
            status="pending",
            rows_migrated=0,
        )
        self._session.add(plan)
        await self._session.flush()
        return plan

    async def transition(
        self, plan_id: int, new_status: str
    ) -> MigrationTablePlanRecord | None:
        """Apply a status transition, enforcing valid transitions.

        Raises :exc:`ValueError` if the transition is not allowed.
        """
        plan = await self.get_by_id(plan_id)
        if plan is None:
            return None
        allowed = self._VALID_TRANSITIONS.get(plan.status, set())
        if new_status not in allowed:
            raise ValueError(
                f"Transition {plan.status!r} → {new_status!r} is not allowed "
                f"(plan_id={plan_id})"
            )
        plan.status = new_status
        await self._session.flush()
        return plan

    async def update_progress(
        self, plan_id: int, rows_migrated: int
    ) -> None:
        """Update migrated row count without changing the status."""
        await self._session.execute(
            update(MigrationTablePlanRecord)
            .where(MigrationTablePlanRecord.migration_table_plan_id == plan_id)
            .values(rows_migrated=rows_migrated)
        )

    async def bulk_create_plans(
        self, job_id: str, table_plans: list[dict[str, Any]]
    ) -> list[MigrationTablePlanRecord]:
        """Insert multiple table plans in one flush.

        *table_plans* is a list of dicts with keys matching
        :meth:`create_plan` keyword arguments.
        """
        records = []
        for tp in table_plans:
            record = MigrationTablePlanRecord(
                migration_job_id=job_id,
                table_name=tp["table_name"],
                schema_name=tp.get("schema_name", "dbo"),
                strategy=tp.get("strategy", "chunked"),
                chunk_size=tp.get("chunk_size", 10_000),
                parallel_workers=tp.get("parallel_workers", 4),
                row_count_estimate=tp.get("row_count_estimate", 0),
                status="pending",
                rows_migrated=0,
            )
            self._session.add(record)
            records.append(record)
        await self._session.flush()
        return records
