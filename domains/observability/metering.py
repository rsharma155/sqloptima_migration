"""Usage metering from audit trail (§13.8).
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.metadata_db.models import AuditLogRecord, MigrationJobRecord


class UsageMeteringService:
    """Aggregate billable usage signals from persisted metadata."""

    async def summary(self, session: AsyncSession, *, days: int = 30) -> dict[str, Any]:
        since = datetime.now(UTC) - timedelta(days=days)

        migrations = await session.execute(
            select(func.count())
            .select_from(MigrationJobRecord)
            .where(MigrationJobRecord.created_at >= since)
        )
        rows_migrated = await session.execute(
            select(func.coalesce(func.sum(MigrationJobRecord.rows_migrated), 0))
            .where(MigrationJobRecord.created_at >= since)
        )
        audit_events = await session.execute(
            select(func.count())
            .select_from(AuditLogRecord)
            .where(AuditLogRecord.timestamp >= since)
        )
        logins = await session.execute(
            select(func.count())
            .select_from(AuditLogRecord)
            .where(
                AuditLogRecord.timestamp >= since,
                AuditLogRecord.action == "user.login",
            )
        )

        return {
            "period_days": days,
            "migration_jobs_started": int(migrations.scalar_one() or 0),
            "rows_migrated": int(rows_migrated.scalar_one() or 0),
            "audit_events": int(audit_events.scalar_one() or 0),
            "login_events": int(logins.scalar_one() or 0),
        }
