"""Unit tests for Go-engine progress snapshots from metadata."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from application.migration_service import build_progress_snapshot
from domains.migration.migration_engine import (
    MigrationJob,
    MigrationStatus,
    MigrationStrategy,
    TableMigrationPlan,
)


def test_build_progress_snapshot_from_table_plans():
    job = MigrationJob(
        job_id=uuid4(),
        status=MigrationStatus.RUNNING,
        created_at=datetime.now(UTC),
        tables=[
            TableMigrationPlan(
                table_name="SystemLogs",
                schema_name="dbo",
                columns=["Id"],
                row_count_estimate=1000,
                rows_migrated=250,
                status="migrating",
                strategy=MigrationStrategy.CHUNKED,
            ),
        ],
    )
    job.started_at = datetime.now(UTC)

    snap = build_progress_snapshot(job)
    assert snap["total_rows_migrated"] == 250
    assert snap["total_rows_estimate"] == 1000
    assert snap["overall_percentage"] == 25.0
    assert snap["tables_progress"]["SystemLogs"]["status"] == "migrating"


def test_build_progress_snapshot_completed_without_row_estimate():
    job = MigrationJob(
        job_id=uuid4(),
        status=MigrationStatus.RUNNING,
        created_at=datetime.now(UTC),
        tables=[
            TableMigrationPlan(
                table_name="Customers",
                schema_name="dbo",
                columns=["Id"],
                row_count_estimate=0,
                rows_migrated=1_000_000,
                status="completed",
                strategy=MigrationStrategy.CHUNKED,
            ),
        ],
    )
    job.started_at = datetime.now(UTC)
    job.completed_at = datetime.now(UTC)

    snap = build_progress_snapshot(job)
    assert snap["overall_percentage"] == 100.0
    assert snap["total_rows_migrated"] == 1_000_000
    assert snap["tables_progress"]["Customers"]["percentage"] == 100.0
    assert snap["status"] == MigrationStatus.COMPLETED
