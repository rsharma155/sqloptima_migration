"""
Module: replication_stream_repository.py
Purpose: Persistence for replication stream aggregate roots
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.metadata_db.models import ReplicationStreamRecord


class ReplicationStreamRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, record: ReplicationStreamRecord) -> ReplicationStreamRecord:
        self._session.add(record)
        await self._session.commit()
        await self._session.refresh(record)
        return record

    async def get(self, stream_id: str) -> ReplicationStreamRecord | None:
        return await self._session.get(ReplicationStreamRecord, stream_id)

    async def list_streams(self) -> list[ReplicationStreamRecord]:
        result = await self._session.execute(
            select(ReplicationStreamRecord).order_by(ReplicationStreamRecord.created_at.desc())
        )
        return list(result.scalars().all())

    async def update_status(
        self,
        stream_id: str,
        *,
        status: str,
        error_message: str | None = None,
        last_checkpoint_lsn: str | None = None,
        events_captured: int | None = None,
        events_applied: int | None = None,
        started_at: datetime | None = None,
        stopped_at: datetime | None = None,
        concerns_json: list[dict[str, Any]] | None = None,
    ) -> ReplicationStreamRecord | None:
        record = await self.get(stream_id)
        if record is None:
            return None
        record.status = status
        record.updated_at = datetime.now(UTC)
        if error_message is not None:
            record.error_message = error_message
        if last_checkpoint_lsn is not None:
            record.last_checkpoint_lsn = last_checkpoint_lsn
        if events_captured is not None:
            record.events_captured = events_captured
        if events_applied is not None:
            record.events_applied = events_applied
        if started_at is not None:
            record.started_at = started_at
        if stopped_at is not None:
            record.stopped_at = stopped_at
        if concerns_json is not None:
            record.concerns_json = concerns_json
        await self._session.commit()
        await self._session.refresh(record)
        return record

    async def update_record(
        self,
        stream_id: str,
        *,
        stream_name: str | None = None,
        project_connection_id: str | None = None,
        target_project_connection_id: str | None = None,
        config_json: dict[str, Any] | None = None,
        concerns_json: list[dict[str, Any]] | None = None,
        status: str | None = None,
        error_message: str | None = None,
    ) -> ReplicationStreamRecord | None:
        record = await self.get(stream_id)
        if record is None:
            return None
        if stream_name is not None:
            record.stream_name = stream_name
        if project_connection_id is not None:
            record.project_connection_id = project_connection_id
        if target_project_connection_id is not None:
            record.target_project_connection_id = target_project_connection_id
        if config_json is not None:
            record.config_json = config_json
        if concerns_json is not None:
            record.concerns_json = concerns_json
        if status is not None:
            record.status = status
        if error_message is not None:
            record.error_message = error_message
        record.updated_at = datetime.now(UTC)
        await self._session.commit()
        await self._session.refresh(record)
        return record

    async def delete(self, stream_id: str) -> bool:
        record = await self.get(stream_id)
        if record is None:
            return False
        await self._session.delete(record)
        await self._session.commit()
        return True
