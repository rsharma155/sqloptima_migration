"""Unit tests for migration job status derivation from metadata."""

from __future__ import annotations

from uuid import uuid4

from application.migration_service import _derive_job_status
from domains.migration.migration_engine import (
    MigrationJob,
    MigrationStatus,
    MigrationStrategy,
    TableMigrationPlan,
)


def _job(*, status: MigrationStatus, table_status: str = "pending") -> MigrationJob:
    return MigrationJob(
        job_id=uuid4(),
        status=status,
        tables=[
            TableMigrationPlan(
                table_name="Bookings",
                schema_name="dbo",
                columns=["Id"],
                row_count_estimate=1_000_000,
                strategy=MigrationStrategy.CHUNKED,
                status=table_status,
            ),
        ],
    )


class _Record:
    def __init__(self, status: str, *, tables_total: int = 0, tables_done: int = 0) -> None:
        self.status = status
        self.table_plans = []
        self.tables_total = tables_total
        self.tables_done = tables_done


def test_derive_completed_when_go_job_data_complete_but_db_running():
    job = _job(status=MigrationStatus.RUNNING, table_status="completed")
    plan = type("Plan", (), {"status": "completed"})()
    record = _Record("running", tables_total=1, tables_done=1)
    record.table_plans = [plan]
    assert _derive_job_status(job, record) == MigrationStatus.COMPLETED


def test_derive_running_from_durable_db_over_stale_queued():
    job = _job(status=MigrationStatus.QUEUED, table_status="migrating")
    assert _derive_job_status(job, _Record("running")) == MigrationStatus.RUNNING


def test_derive_running_from_table_migrating_status():
    job = _job(status=MigrationStatus.QUEUED, table_status="migrating")
    assert _derive_job_status(job, None) == MigrationStatus.RUNNING


def test_derive_partial_when_some_tables_failed():
    job = MigrationJob(
        job_id=uuid4(),
        status=MigrationStatus.RUNNING,
        tables=[
            TableMigrationPlan(
                table_name="good",
                schema_name="dbo",
                columns=["Id"],
                row_count_estimate=1,
                strategy=MigrationStrategy.CHUNKED,
                status="completed",
            ),
            TableMigrationPlan(
                table_name="bad",
                schema_name="dbo",
                columns=["Id"],
                row_count_estimate=1,
                strategy=MigrationStrategy.CHUNKED,
                status="failed",
            ),
        ],
    )
    assert _derive_job_status(job, None) == MigrationStatus.PARTIAL


def test_derive_failed_when_all_tables_failed():
    job = MigrationJob(
        job_id=uuid4(),
        status=MigrationStatus.RUNNING,
        tables=[
            TableMigrationPlan(
                table_name="bad",
                schema_name="dbo",
                columns=["Id"],
                row_count_estimate=1,
                strategy=MigrationStrategy.CHUNKED,
                status="failed",
            ),
        ],
    )
    assert _derive_job_status(job, None) == MigrationStatus.FAILED


def test_derive_terminal_db_status_wins():
    job = _job(status=MigrationStatus.RUNNING, table_status="migrating")
    assert _derive_job_status(job, _Record("failed")) == MigrationStatus.FAILED
