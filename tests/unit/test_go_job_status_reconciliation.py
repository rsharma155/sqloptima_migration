"""Tests for Go job status reconciliation and save_jobs_async status safety."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("METADATA_DB_URL", "sqlite+aiosqlite:///:memory:")

from application.migration_service import (
    _go_job_data_complete,
    _reconcile_go_job_completion,
    save_jobs_async,
)
from application.job_registry import JobRegistry
from domains.migration.migration_engine import (
    MigrationJob,
    MigrationStatus,
    MigrationStrategy,
    TableMigrationPlan,
)
from infrastructure.metadata_db.models import Base, MigrationJobRecord, MigrationTablePlanRecord


@pytest.fixture
async def metadata_session() -> AsyncSession:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as sess:
        yield sess

    await engine.dispose()


def _completed_go_record(job_id) -> MigrationJobRecord:
    return MigrationJobRecord(
        migration_job_id=str(job_id),
        status="running",
        executor="go",
        tables_total=1,
        tables_done=1,
        rows_total=100,
        rows_migrated=100,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_go_job_data_complete_detects_finished_tables(metadata_session: AsyncSession):
    job_id = uuid4()
    record = _completed_go_record(job_id)
    metadata_session.add(record)
    metadata_session.add(
        MigrationTablePlanRecord(
            migration_job_id=str(job_id),
            table_name="t1",
            schema_name="dbo",
            target_schema="public",
            strategy="chunked",
            status="completed",
            rows_migrated=100,
            row_count_estimate=100,
        )
    )
    await metadata_session.commit()
    await metadata_session.refresh(record, ["table_plans"])
    assert _go_job_data_complete(record) is True


@pytest.mark.asyncio
async def test_reconcile_promotes_stuck_running_to_completed(metadata_session: AsyncSession):
    job_id = uuid4()
    record = _completed_go_record(job_id)
    metadata_session.add(record)
    metadata_session.add(
        MigrationTablePlanRecord(
            migration_job_id=str(job_id),
            table_name="t1",
            schema_name="dbo",
            target_schema="public",
            strategy="chunked",
            status="completed",
            rows_migrated=100,
            row_count_estimate=100,
        )
    )
    await metadata_session.commit()
    await metadata_session.refresh(record, ["table_plans"])

    changed = await _reconcile_go_job_completion(metadata_session, record)
    assert changed is True
    assert record.status == "completed"
    assert record.completed_at is not None


@pytest.mark.asyncio
async def test_save_jobs_async_does_not_clobber_go_completed_status(metadata_session: AsyncSession):
    job_id = uuid4()
    record = _completed_go_record(job_id)
    record.status = "completed"
    record.completed_at = datetime.now(UTC)
    metadata_session.add(record)
    await metadata_session.commit()

    registry = JobRegistry()
    registry.put(
        MigrationJob(
            job_id=job_id,
            status=MigrationStatus.RUNNING,
            executor="go",
            tables=[
                TableMigrationPlan(
                    table_name="t1",
                    schema_name="dbo",
                    columns=["id"],
                    row_count_estimate=100,
                    strategy=MigrationStrategy.CHUNKED,
                    status="migrating",
                ),
            ],
        )
    )

    session_factory = async_sessionmaker(
        metadata_session.bind, expire_on_commit=False, class_=AsyncSession
    )

    with patch("application.migration_service.AsyncSessionFactory", session_factory), patch(
        "application.migration_service._registry", registry
    ):
        await save_jobs_async(force=True)

    refreshed = await metadata_session.get(MigrationJobRecord, str(job_id))
    assert refreshed is not None
    assert refreshed.status == "completed"
