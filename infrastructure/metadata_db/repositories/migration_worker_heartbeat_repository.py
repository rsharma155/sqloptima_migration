"""Repository for Go migration-engine worker heartbeats.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.metadata_db.models import MigrationWorkerHeartbeatRecord


class MigrationWorkerHeartbeatRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self,
        worker_id: str,
        *,
        engine_version: str = "0.2.0",
        status: str = "idle",
    ) -> MigrationWorkerHeartbeatRecord:
        record = await self._session.get(MigrationWorkerHeartbeatRecord, worker_id)
        now = datetime.now(UTC)
        if record is None:
            record = MigrationWorkerHeartbeatRecord(
                worker_id=worker_id,
                last_seen_at=now,
                engine_version=engine_version,
                status=status,
            )
            self._session.add(record)
        else:
            record.last_seen_at = now
            record.engine_version = engine_version
            record.status = status
        await self._session.commit()
        await self._session.refresh(record)
        return record

    async def list_all(self) -> list[MigrationWorkerHeartbeatRecord]:
        result = await self._session.execute(
            select(MigrationWorkerHeartbeatRecord).order_by(
                MigrationWorkerHeartbeatRecord.last_seen_at.desc()
            )
        )
        return list(result.scalars().all())

    async def has_recent_heartbeat(self, *, within_seconds: int = 60) -> bool:
        cutoff = datetime.now(UTC) - timedelta(seconds=within_seconds)
        result = await self._session.execute(
            select(MigrationWorkerHeartbeatRecord.worker_id).where(
                MigrationWorkerHeartbeatRecord.last_seen_at >= cutoff
            ).limit(1)
        )
        return result.scalar_one_or_none() is not None
