"""Platform alert aggregation for dashboard and global UI banners.

Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import application.migration_service as migration_svc
from domains.migration.migration_engine import MigrationStatus


@dataclass
class PlatformAlert:
    id: str
    severity: str  # critical | warning | info
    category: str
    title: str
    message: str
    href: str | None = None
    resource_id: str | None = None
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def notification_config_status() -> dict[str, Any]:
    webhook = bool(os.environ.get("MIGRATION_WEBHOOK_URL"))
    smtp_host = os.environ.get("MIGRATION_SMTP_HOST", "")
    email_to = os.environ.get("MIGRATION_ALERT_EMAIL_TO", "")
    email_configured = bool(smtp_host and email_to)
    return {
        "webhook_configured": webhook,
        "email_configured": email_configured,
        "email_to": email_to if email_configured else None,
        "channels_active": webhook or email_configured,
    }


class AlertService:
    """Collect actionable platform alerts from in-process migration state."""

    def __init__(self, *, recent_failure_hours: int = 72) -> None:
        self._recent_failure_hours = recent_failure_hours

    def collect(self, project_id: str | None = None) -> list[PlatformAlert]:
        alerts: list[PlatformAlert] = []
        cutoff = datetime.now(UTC) - timedelta(hours=self._recent_failure_hours)

        for jid, job in migration_svc.list_jobs(project_id=project_id):
            status = (
                job.status.value if hasattr(job.status, "value") else str(job.status)
            ).lower()
            created = getattr(job, "created_at", None)
            updated = getattr(job, "updated_at", created)
            ts = updated or created
            if ts and ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)

            if status == MigrationStatus.FAILED.value:
                if ts and ts < cutoff:
                    continue
                err = getattr(job, "error_message", None) or "Unknown error"
                alerts.append(
                    PlatformAlert(
                        id=f"migration-failed-{jid}",
                        severity="critical",
                        category="migration",
                        title="Migration failed",
                        message=f"Job {str(jid)[:8]}… failed: {err[:200]}",
                        href=f"/migrations/{jid}",
                        resource_id=str(jid),
                        created_at=ts.isoformat() if ts else _now_iso(),
                    )
                )
            elif status == MigrationStatus.STOPPED.value:
                if ts and ts < cutoff:
                    continue
                alerts.append(
                    PlatformAlert(
                        id=f"migration-stopped-{jid}",
                        severity="warning",
                        category="migration",
                        title="Migration stopped",
                        message=f"Job {str(jid)[:8]}… was stopped manually.",
                        href=f"/migrations/{jid}",
                        resource_id=str(jid),
                        created_at=ts.isoformat() if ts else _now_iso(),
                    )
                )
            elif status in (MigrationStatus.RUNNING.value, MigrationStatus.PENDING.value):
                if ts and datetime.now(UTC) - ts > timedelta(hours=6):
                    alerts.append(
                        PlatformAlert(
                            id=f"migration-stale-{jid}",
                            severity="warning",
                            category="migration",
                            title="Long-running migration",
                            message=(
                                f"Job {str(jid)[:8]}… has been {status} for over 6 hours. "
                                "Verify progress or check for a stuck worker."
                            ),
                            href=f"/migrations/{jid}",
                            resource_id=str(jid),
                            created_at=ts.isoformat() if ts else _now_iso(),
                        )
                    )

        alerts.extend(self._connection_alerts())
        alerts.extend(self._notification_alerts())

        alerts.sort(
            key=lambda a: (
                _SEVERITY_ORDER.get(a.severity, 9),
                a.created_at,
            ),
        )
        return alerts

    def _connection_alerts(self) -> list[PlatformAlert]:
        from apps.api.connection_store import get_all

        conns = get_all()
        sources = [c for c in conns.values() if c.get("type") == "source"]
        targets = [c for c in conns.values() if c.get("type") == "target"]
        alerts: list[PlatformAlert] = []
        if not sources:
            alerts.append(
                PlatformAlert(
                    id="connection-no-source",
                    severity="warning",
                    category="connection",
                    title="No source connection",
                    message="Add a SQL Server source connection in Settings before migrating.",
                    href="/settings",
                    created_at=_now_iso(),
                )
            )
        if not targets:
            alerts.append(
                PlatformAlert(
                    id="connection-no-target",
                    severity="warning",
                    category="connection",
                    title="No target connection",
                    message="Add a PostgreSQL target connection in Settings before migrating.",
                    href="/settings",
                    created_at=_now_iso(),
                )
            )
        return alerts

    def _notification_alerts(self) -> list[PlatformAlert]:
        cfg = notification_config_status()
        if cfg["channels_active"]:
            return []
        return [
            PlatformAlert(
                id="notification-not-configured",
                severity="info",
                category="notification",
                title="External alerting not configured",
                message=(
                    "Set MIGRATION_WEBHOOK_URL and/or MIGRATION_SMTP_HOST + "
                    "MIGRATION_ALERT_EMAIL_TO in .env to receive email/Slack alerts "
                    "when migrations fail overnight."
                ),
                href="/settings",
                created_at=_now_iso(),
            )
        ]

    def summary(self, alerts: list[PlatformAlert]) -> dict[str, int]:
        return {
            "total": len(alerts),
            "critical": sum(1 for a in alerts if a.severity == "critical"),
            "warning": sum(1 for a in alerts if a.severity == "warning"),
            "info": sum(1 for a in alerts if a.severity == "info"),
        }
