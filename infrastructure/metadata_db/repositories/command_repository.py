"""Repository for migration_commands — pause/resume/stop issued by the API.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.metadata_db.models import MigrationCommandRecord


class CommandRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_command(self, job_id: str) -> MigrationCommandRecord | None:
        return await self._session.get(MigrationCommandRecord, job_id)

    async def issue(self, job_id: str, command: str) -> MigrationCommandRecord:
        """Upsert a command for the job (one active command per job at a time)."""
        record = MigrationCommandRecord(
            migration_job_id=job_id,
            command=command,
            issued_at=datetime.now(UTC),
            acked_at=None,
        )
        merged = await self._session.merge(record)
        await self._session.commit()
        await self._notify_worker(job_id)
        return merged

    async def _notify_worker(self, job_id: str) -> None:
        """Wake Go workers listening on migration_commands via PostgreSQL NOTIFY."""
        bind = self._session.get_bind()
        if bind.dialect.name != "postgresql":
            return

        from sqlalchemy import text

        await self._session.execute(
            text("SELECT pg_notify('migration_commands', :job_id)"),
            {"job_id": job_id},
        )
        await self._session.commit()

    async def acknowledge(self, job_id: str) -> None:
        """Mark the current command as acknowledged by the worker."""
        record = await self.get_command(job_id)
        if record:
            record.acked_at = datetime.now(UTC)
            await self._session.commit()

    async def clear(self, job_id: str) -> None:
        """Remove the command once it's been fully acted upon."""
        record = await self.get_command(job_id)
        if record:
            await self._session.delete(record)
            await self._session.commit()
