"""Repository for append-only platform audit log entries.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.metadata_db.models import AuditLogRecord, TokenDenylistRecord


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, record: AuditLogRecord) -> AuditLogRecord:
        self._session.add(record)
        await self._session.commit()
        return record

    async def query(
        self,
        *,
        action: str | None = None,
        actor: str | None = None,
        resource: str | None = None,
        project_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditLogRecord]:
        stmt = select(AuditLogRecord).order_by(AuditLogRecord.timestamp.desc())
        if action:
            stmt = stmt.where(AuditLogRecord.action == action)
        if actor:
            stmt = stmt.where(AuditLogRecord.actor == actor)
        if resource:
            stmt = stmt.where(AuditLogRecord.resource.contains(resource))
        if project_id:
            stmt = stmt.where(AuditLogRecord.project_id == project_id)
        stmt = stmt.limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def revoke_token(self, jti: str, expires_at: datetime) -> None:
        self._session.add(
            TokenDenylistRecord(
                jti=jti,
                expires_at=expires_at,
                revoked_at=datetime.now(UTC),
            )
        )
        await self._session.commit()

    async def is_token_revoked(self, jti: str) -> bool:
        result = await self._session.execute(
            select(TokenDenylistRecord).where(TokenDenylistRecord.jti == jti)
        )
        return result.scalar_one_or_none() is not None

    async def purge_expired_tokens(self) -> int:
        now = datetime.now(UTC)
        result = await self._session.execute(
            delete(TokenDenylistRecord).where(TokenDenylistRecord.expires_at < now)
        )
        await self._session.commit()
        return result.rowcount or 0
