"""Unit tests for migration pause eligibility and DB hydration."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from application.job_registry import JobRegistry
from application.migration_service import _can_pause_job, pause_job
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


def test_can_pause_pending_job_with_migrating_tables():
    job = MigrationJob(
        job_id=uuid4(),
        status=MigrationStatus.PENDING,
        executor="go",
        tables=[
            TableMigrationPlan(
                table_name="orders",
                schema_name="dbo",
                columns=["id"],
                row_count_estimate=100,
                strategy=MigrationStrategy.CHUNKED,
                status="migrating",
            ),
        ],
    )
    assert _can_pause_job(job, None) is True


def test_can_pause_rejects_completed_job():
    job = MigrationJob(
        job_id=uuid4(),
        status=MigrationStatus.COMPLETED,
        executor="go",
        tables=[],
    )
    assert _can_pause_job(job, None) is False


@pytest.mark.asyncio
async def test_pause_hydrates_job_from_metadata_when_registry_empty(metadata_session: AsyncSession):
    job_id = uuid4()
    record = MigrationJobRecord(
        migration_job_id=str(job_id),
        status="pending",
        executor="go",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    record.table_plans = [
        MigrationTablePlanRecord(
            migration_job_id=str(job_id),
            table_name="orders",
            schema_name="dbo",
            strategy="chunked",
            status="migrating",
            columns=["id"],
        ),
    ]
    await metadata_session.merge(record)
    await metadata_session.commit()

    registry = JobRegistry()
    session_factory = async_sessionmaker(
        metadata_session.bind, expire_on_commit=False, class_=AsyncSession
    )

    with patch("application.migration_service.AsyncSessionFactory", session_factory), patch(
        "application.go_engine_migration.durable_migration_job_log_writer.AsyncSessionFactory",
        session_factory,
    ), patch(
        "application.migration_service._registry", registry
    ), patch(
        "infrastructure.metadata_db.repositories.command_repository.CommandRepository.issue",
        new_callable=AsyncMock,
    ):
        result = await pause_job(job_id)

    assert result.status == MigrationStatus.PAUSED
    assert registry.get(job_id) is not None


@pytest.mark.asyncio
async def test_pause_rejects_completed_job(metadata_session: AsyncSession):
    job_id = uuid4()
    await metadata_session.merge(
        MigrationJobRecord(
            migration_job_id=str(job_id),
            status="completed",
            executor="go",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
    await metadata_session.commit()

    registry = JobRegistry()
    job = MigrationJob(job_id=job_id, status=MigrationStatus.COMPLETED, executor="go")
    registry.put(job)

    session_factory = async_sessionmaker(
        metadata_session.bind, expire_on_commit=False, class_=AsyncSession
    )

    with patch("application.migration_service.AsyncSessionFactory", session_factory), patch(
        "application.migration_service._registry", registry
    ):
        with pytest.raises(ValueError, match="not running"):
            await pause_job(job_id)
