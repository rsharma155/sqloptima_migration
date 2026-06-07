"""
Module: audit_log.py
Purpose: Encryption and secrets management
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)


class AuditAction(StrEnum):
    MIGRATION_STARTED = "migration.started"
    MIGRATION_COMPLETED = "migration.completed"
    MIGRATION_FAILED = "migration.failed"
    MIGRATION_PAUSED = "migration.paused"
    MIGRATION_RESUMED = "migration.resumed"
    MIGRATION_STOPPED = "migration.stopped"
    CHUNK_STARTED = "chunk.started"
    CHUNK_COMPLETED = "chunk.completed"
    CHUNK_FAILED = "chunk.failed"
    CHUNK_QUARANTINED = "chunk.quarantined"
    TABLE_MIGRATED = "table.migrated"
    DISCOVERY_STARTED = "discovery.started"
    DISCOVERY_COMPLETED = "discovery.completed"
    CONVERSION_STARTED = "conversion.started"
    CONVERSION_COMPLETED = "conversion.completed"
    VALIDATION_STARTED = "validation.started"
    VALIDATION_COMPLETED = "validation.completed"
    USER_LOGIN = "user.login"
    USER_LOGOUT = "user.logout"
    PERMISSION_CHANGE = "permission.change"
    CONFIG_CHANGE = "config.change"
    DATA_ACCESS = "data.access"


class AuditLogEntry(BaseModel):
    entry_id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    action: AuditAction
    actor: str
    resource: str
    details: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str | None = None
    source_ip: str | None = None
    success: bool = True
    error_message: str | None = None


AUDIT_LOG_DDL = """
CREATE TABLE IF NOT EXISTS _audit_log (
    entry_id          UUID PRIMARY KEY,
    timestamp         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    action            TEXT NOT NULL,
    actor             TEXT NOT NULL,
    resource          TEXT NOT NULL,
    details           JSONB DEFAULT '{}'::jsonb,
    correlation_id    TEXT,
    source_ip         TEXT,
    success           BOOLEAN NOT NULL DEFAULT TRUE,
    error_message     TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON _audit_log(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_action ON _audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_log_actor ON _audit_log(actor);
CREATE INDEX IF NOT EXISTS idx_audit_log_resource ON _audit_log(resource);
"""


class AuditLogger:
    def __init__(self, connector: Any):
        self._connector = connector

    async def ensure_table(self) -> None:
        await self._connector.execute(AUDIT_LOG_DDL)

    async def record(self, entry: AuditLogEntry) -> None:
        sql = """
        INSERT INTO _audit_log (
            entry_id, timestamp, action, actor, resource,
            details, correlation_id, source_ip, success, error_message
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        """
        try:
            await self._connector.execute(sql, {
                "entry_id": str(entry.entry_id),
                "timestamp": entry.timestamp,
                "action": entry.action.value,
                "actor": entry.actor,
                "resource": entry.resource,
                "details": entry.details,
                "correlation_id": entry.correlation_id,
                "source_ip": entry.source_ip,
                "success": entry.success,
                "error_message": entry.error_message,
            })
        except Exception as e:
            logger.error("Failed to write audit log", error=str(e), action=entry.action.value)

    async def record_action(
        self,
        action: AuditAction,
        actor: str,
        resource: str,
        details: dict[str, Any] | None = None,
        correlation_id: str | None = None,
        source_ip: str | None = None,
        success: bool = True,
        error_message: str | None = None,
    ) -> None:
        entry = AuditLogEntry(
            action=action,
            actor=actor,
            resource=resource,
            details=details or {},
            correlation_id=correlation_id,
            source_ip=source_ip,
            success=success,
            error_message=error_message,
        )
        await self.record(entry)

    async def query(
        self,
        action: AuditAction | None = None,
        actor: str | None = None,
        resource: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditLogEntry]:
        conditions: list[str] = []
        params: dict[str, Any] = {}
        idx = 1
        if action:
            conditions.append(f"action = ${idx}")
            params[f"p{idx}"] = action.value
            idx += 1
        if actor:
            conditions.append(f"actor = ${idx}")
            params[f"p{idx}"] = actor
            idx += 1
        if resource:
            conditions.append(f"resource = ${idx}")
            params[f"p{idx}"] = resource
            idx += 1
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        sql = f"""
        SELECT * FROM _audit_log{where}
        ORDER BY timestamp DESC
        LIMIT ${idx} OFFSET ${idx + 1}
        """
        params[f"p{idx}"] = limit
        params[f"p{idx + 1}"] = offset
        rows = await self._connector.execute(sql, params)
        return [AuditLogEntry(**r) for r in rows]
