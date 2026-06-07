"""Cutover checkpoint persistence and rollback execution (§13.2).
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.metadata_db.models import CutoverCheckpointRecord
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)


@dataclass
class CutoverCheckpoint:
    job_id: str
    tables: list[str]
    schema: str = "dbo"
    target_schema: str = "public"
    checkpoint_lsn: str = "FINAL"
    row_counts: dict[str, int] | None = None
    snapshot_ref: str | None = None
    committed: bool = False
    writes_frozen_at: datetime | None = None
    source_row_counts: dict[str, int] | None = None
    connection_switch: dict | None = None


class CutoverService:
    """Persist cutover checkpoints and execute rollback to pre-cutover state."""

    def __init__(self, session: AsyncSession, target_connector: Any | None = None) -> None:
        self._session = session
        self._target = target_connector

    async def save_checkpoint(self, checkpoint: CutoverCheckpoint) -> CutoverCheckpointRecord:
        record = CutoverCheckpointRecord(
            cutover_checkpoint_id=str(uuid4()),
            migration_job_id=checkpoint.job_id,
            tables=checkpoint.tables,
            schema_name=checkpoint.schema,
            target_schema=checkpoint.target_schema,
            checkpoint_lsn=checkpoint.checkpoint_lsn,
            row_counts=checkpoint.row_counts or {},
            snapshot_ref=checkpoint.snapshot_ref,
            committed=checkpoint.committed,
            writes_frozen_at=checkpoint.writes_frozen_at,
            source_row_counts=checkpoint.source_row_counts,
            connection_switch=checkpoint.connection_switch,
            created_at=datetime.now(UTC),
        )
        self._session.add(record)
        await self._session.commit()
        logger.info(
            "cutover_checkpoint_saved",
            job_id=checkpoint.job_id,
            tables=len(checkpoint.tables),
        )
        return record

    async def get_latest_checkpoint(self, job_id: str) -> CutoverCheckpointRecord | None:
        result = await self._session.execute(
            select(CutoverCheckpointRecord)
            .where(CutoverCheckpointRecord.migration_job_id == job_id)
            .order_by(CutoverCheckpointRecord.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def record_write_freeze(
        self,
        job_id: str,
        *,
        frozen_at: datetime,
        source_row_counts: dict[str, int],
    ) -> None:
        record = await self.get_latest_checkpoint(job_id)
        if record:
            record.writes_frozen_at = frozen_at
            record.source_row_counts = source_row_counts
            await self._session.commit()

    async def store_connection_switch(self, job_id: str, manifest: dict) -> None:
        record = await self.get_latest_checkpoint(job_id)
        if record:
            record.connection_switch = manifest
            await self._session.commit()

    async def mark_committed(self, job_id: str) -> None:
        record = await self.get_latest_checkpoint(job_id)
        if record:
            record.committed = True
            record.committed_at = datetime.now(UTC)
            await self._session.commit()

    async def rollback(self, job_id: str) -> dict[str, Any]:
        """Rollback cutover by truncating target tables listed in the checkpoint.

        Returns a summary dict.  If ``snapshot_ref`` is set, includes it so the
        operator can restore from an external pg_dump instead.
        """
        record = await self.get_latest_checkpoint(job_id)
        if not record:
            return {"success": False, "error": "No cutover checkpoint found for job"}
        if record.committed:
            return {
                "success": False,
                "error": "Cutover already committed — rollback window closed",
                "committed_at": record.committed_at.isoformat() if record.committed_at else None,
            }

        truncated: list[str] = []
        errors: list[str] = []

        if self._target is not None:
            for table in record.tables or []:
                qualified = f'"{record.target_schema}"."{table}"'
                try:
                    await self._target.execute(f"TRUNCATE TABLE {qualified} CASCADE")
                    truncated.append(table)
                except Exception as exc:
                    errors.append(f"{table}: {exc}")

        record.rolled_back_at = datetime.now(UTC)
        await self._session.commit()

        return {
            "success": len(errors) == 0,
            "job_id": job_id,
            "tables_truncated": truncated,
            "snapshot_ref": record.snapshot_ref,
            "errors": errors,
            "message": (
                "Target tables truncated to pre-cutover state"
                if not record.snapshot_ref
                else f"Tables truncated; restore from snapshot: {record.snapshot_ref}"
            ),
        }
