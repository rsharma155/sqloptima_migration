"""Unit tests for AlertService."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import application.migration_service as migration_svc
from application.alert_service import AlertService, notification_config_status
from application.job_registry import JobRegistry
from domains.migration.migration_engine import (
    MigrationJob,
    MigrationStatus,
    MigrationStrategy,
    TableMigrationPlan,
)


def _make_job(status: MigrationStatus, *, error: str | None = None) -> MigrationJob:
    return MigrationJob(
        job_id=uuid4(),
        status=status,
        error_message=error,
        updated_at=datetime.now(UTC),
        tables=[
            TableMigrationPlan(
                table_name="users",
                schema_name="dbo",
                columns=["*"],
                row_count_estimate=100,
                strategy=MigrationStrategy.CHUNKED,
            )
        ],
    )


class TestAlertService:
    def test_failed_migration_produces_critical_alert(self, monkeypatch) -> None:
        job = _make_job(MigrationStatus.FAILED, error="Connection refused")
        jid = job.job_id
        registry = JobRegistry()
        registry.put(job)
        monkeypatch.setattr(migration_svc, "_registry", registry)
        monkeypatch.setattr(migration_svc, "list_jobs", lambda project_id=None: [(jid, job)])

        alerts = AlertService().collect()
        failed = [a for a in alerts if a.category == "migration" and a.severity == "critical"]
        assert len(failed) == 1
        assert "Connection refused" in failed[0].message

    def test_stale_running_job_warning(self, monkeypatch) -> None:
        job = _make_job(MigrationStatus.RUNNING)
        job.updated_at = datetime.now(UTC) - timedelta(hours=7)
        jid = job.job_id
        registry = JobRegistry()
        registry.put(job)
        monkeypatch.setattr(migration_svc, "_registry", registry)
        monkeypatch.setattr(migration_svc, "list_jobs", lambda project_id=None: [(jid, job)])

        alerts = AlertService().collect()
        stale = [a for a in alerts if "stale" in a.id]
        assert len(stale) == 1

    def test_notification_config_status(self, monkeypatch) -> None:
        monkeypatch.delenv("MIGRATION_WEBHOOK_URL", raising=False)
        monkeypatch.delenv("MIGRATION_SMTP_HOST", raising=False)
        cfg = notification_config_status()
        assert cfg["channels_active"] is False

        monkeypatch.setenv("MIGRATION_WEBHOOK_URL", "https://example.com/hook")
        cfg = notification_config_status()
        assert cfg["webhook_configured"] is True
        assert cfg["channels_active"] is True
