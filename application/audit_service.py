"""AuditService — durable, append-only audit trail for privileged operations.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.metadata_db.models import AuditLogRecord
from infrastructure.metadata_db.repositories.audit_repository import AuditRepository
from shared.security.audit_log import AuditAction


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = AuditRepository(session)

    async def record(
        self,
        action: AuditAction,
        actor: str,
        resource: str,
        *,
        details: dict[str, Any] | None = None,
        correlation_id: str | None = None,
        source_ip: str | None = None,
        project_id: str | None = None,
        success: bool = True,
        error_message: str | None = None,
    ) -> AuditLogRecord:
        record = AuditLogRecord(
            audit_log_id=str(uuid4()),
            timestamp=datetime.now(UTC),
            action=action.value,
            actor=actor,
            resource=resource,
            details=details or {},
            correlation_id=correlation_id,
            source_ip=source_ip,
            project_id=project_id,
            success=success,
            error_message=error_message,
        )
        return await self._repo.append(record)

    async def query(
        self,
        *,
        action: AuditAction | None = None,
        actor: str | None = None,
        resource: str | None = None,
        project_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditLogRecord]:
        return await self._repo.query(
            action=action.value if action else None,
            actor=actor,
            resource=resource,
            project_id=project_id,
            limit=limit,
            offset=offset,
        )

    async def revoke_access_token(self, jti: str, expires_at: datetime) -> None:
        await self._repo.revoke_token(jti, expires_at)

    async def is_token_revoked(self, jti: str) -> bool:
        return await self._repo.is_token_revoked(jti)

    async def purge_expired_tokens(self) -> int:
        return await self._repo.purge_expired_tokens()
