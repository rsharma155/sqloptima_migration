"""Unit tests for Go migration job watcher."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from application.go_engine_migration.go_migration_job_watcher import watch_go_migration_job
from domains.migration.migration_engine import (
    MigrationJob,
    MigrationStatus,
    MigrationStrategy,
    TableMigrationPlan,
)


@pytest.mark.asyncio
async def test_watcher_runs_validation_on_completed(monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = uuid4()
    job = MigrationJob(
        job_id=job_id,
        status=MigrationStatus.QUEUED,
        validate_after=True,
        tables=[
            TableMigrationPlan(
                table_name="Customers",
                schema_name="dbo",
                columns=["Id"],
                row_count_estimate=0,
                strategy=MigrationStrategy.CHUNKED,
            )
        ],
    )

    calls = {"validate": 0}

    async def fake_refresh(_jid):
        job.status = MigrationStatus.COMPLETED
        return job

    async def fake_validate(*_args, **_kwargs):
        calls["validate"] += 1
        return {"status": "passed", "source_count": 1, "target_count": 1}

    monkeypatch.setattr(
        "application.migration_service.refresh_job_from_metadata",
        fake_refresh,
    )
    monkeypatch.setattr(
        "domains.orchestration.activities.validate_table",
        fake_validate,
    )
    monkeypatch.setattr(
        "application.migration_service.save_jobs_async",
        lambda: asyncio.sleep(0),
    )

    await watch_go_migration_job(job_id, validate_after=True, poll_interval_sec=0.01, timeout_sec=1)
    assert calls["validate"] == 1


@pytest.mark.asyncio
async def test_watcher_skips_validation_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = uuid4()
    job = MigrationJob(
        job_id=job_id,
        status=MigrationStatus.COMPLETED,
        tables=[
            TableMigrationPlan(
                table_name="t",
                schema_name="dbo",
                columns=["id"],
                row_count_estimate=0,
                strategy=MigrationStrategy.CHUNKED,
            )
        ],
    )

    async def fake_refresh(_jid):
        return job

    async def fake_validate(*_args, **_kwargs):
        raise AssertionError("validate_table should not be called")

    monkeypatch.setattr(
        "application.migration_service.refresh_job_from_metadata",
        fake_refresh,
    )
    monkeypatch.setattr(
        "domains.orchestration.activities.validate_table",
        fake_validate,
    )

    await watch_go_migration_job(job_id, validate_after=False, poll_interval_sec=0.01, timeout_sec=1)
