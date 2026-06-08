"""Unit tests for durable pause/resume/stop persistence."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("METADATA_DB_URL", "sqlite+aiosqlite:///:memory:")

from application.migration_service import pause_job, resume_job, stop_job
from application.job_registry import JobRegistry
from domains.migration.migration_engine import (
    MigrationJob,
    MigrationStatus,
    MigrationStrategy,
    TableMigrationPlan,
)
from infrastructure.metadata_db.models import Base, MigrationJobRecord
from infrastructure.metadata_db.repositories.migration_job_log_repository import (
    MigrationJobLogRepository,
)


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


def _running_job(job_id) -> MigrationJob:
    return MigrationJob(
        job_id=job_id,
        status=MigrationStatus.RUNNING,
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


@pytest.mark.asyncio
async def test_pause_persists_status_and_log(metadata_session: AsyncSession):
    job_id = uuid4()
    await metadata_session.merge(
        MigrationJobRecord(
            migration_job_id=str(job_id),
            status="running",
            executor="go",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
    await metadata_session.commit()

    registry = JobRegistry()
    registry.put(_running_job(job_id))

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
    record = await metadata_session.get(MigrationJobRecord, str(job_id))
    assert record is not None
    assert record.status == "paused"

    logs = await MigrationJobLogRepository(metadata_session).list_for_job(str(job_id))
    assert len(logs) == 1
    assert "pause requested" in logs[0].message.lower()


@pytest.mark.asyncio
async def test_resume_persists_status_and_log(metadata_session: AsyncSession):
    job_id = uuid4()
    await metadata_session.merge(
        MigrationJobRecord(
            migration_job_id=str(job_id),
            status="paused",
            executor="go",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
    await metadata_session.commit()

    job = _running_job(job_id)
    job.status = MigrationStatus.PAUSED
    registry = JobRegistry()
    registry.put(job)

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
        result = await resume_job(job_id)

    assert result.status == MigrationStatus.RUNNING
    record = await metadata_session.get(MigrationJobRecord, str(job_id))
    assert record is not None
    assert record.status == "running"

    logs = await MigrationJobLogRepository(metadata_session).list_for_job(str(job_id))
    assert any("resume requested" in log.message.lower() for log in logs)


@pytest.mark.asyncio
async def test_stop_persists_status_and_log(metadata_session: AsyncSession):
    job_id = uuid4()
    await metadata_session.merge(
        MigrationJobRecord(
            migration_job_id=str(job_id),
            status="running",
            executor="go",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
    await metadata_session.commit()

    registry = JobRegistry()
    registry.put(_running_job(job_id))

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
        result = await stop_job(job_id)

    assert result.status == MigrationStatus.STOPPED
    record = await metadata_session.get(MigrationJobRecord, str(job_id))
    assert record is not None
    assert record.status == "stopped"
    assert record.completed_at is not None

    logs = await MigrationJobLogRepository(metadata_session).list_for_job(str(job_id))
    assert any("stop requested" in log.message.lower() for log in logs)
