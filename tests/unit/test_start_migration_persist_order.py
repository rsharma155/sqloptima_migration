"""Ensure new migration jobs are persisted before durable log writes."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("METADATA_DB_URL", "sqlite+aiosqlite:///:memory:")

from application.migration_service import start_migration
from domains.migration.migration_engine import MigrationStrategy
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


@pytest.mark.asyncio
async def test_start_migration_persists_job_before_log(metadata_session: AsyncSession):
    src_id = uuid4()
    tgt_id = uuid4()
    session_factory = async_sessionmaker(
        metadata_session.bind, expire_on_commit=False, class_=AsyncSession
    )

    mock_connector = AsyncMock()
    mock_connector.connect = AsyncMock()
    mock_connector.disconnect = AsyncMock()
    mock_connector.execute = AsyncMock(return_value=[{"exists": False}])

    with patch("application.migration_service.AsyncSessionFactory", session_factory), patch(
        "application.go_engine_migration.durable_migration_job_log_writer.AsyncSessionFactory",
        session_factory,
    ), patch(
        "apps.api.connection_store.get_entry",
        side_effect=lambda cid: {
            "type": "source" if cid == str(src_id) else "target",
            "host": "127.0.0.1",
            "port": 5432 if cid != str(src_id) else 1433,
            "database": "db",
            "username": "u",
            "password": "p",
            "project_id": None,
        },
    ), patch(
        "application.migration_service.make_connector",
        new=AsyncMock(return_value=(mock_connector, None)),
    ), patch(
        "application.migration_service._resolve_masking_for_tables",
        new=AsyncMock(return_value={"t1": ({}, {}, None)}),
    ), patch(
        "application.migration_service._record_migration_audit",
        new=AsyncMock(),
    ), patch(
        "application.migration_service.create_notification_service",
    ) as notifier_cls, patch(
        "application.migration_service._dispatch_go_migration_job",
        new=AsyncMock(),
    ):
        notifier_cls.return_value.job_started = AsyncMock()
        job = await start_migration(
            source_connection_id=src_id,
            target_connection_id=tgt_id,
            tables=["t1"],
            schema="dbo",
            strategy=MigrationStrategy.CHUNKED,
            chunk_size=1000,
            parallel_workers=1,
            require_target_snapshot=False,
        )

    record = await metadata_session.get(MigrationJobRecord, str(job.job_id))
    assert record is not None
    logs = await MigrationJobLogRepository(metadata_session).list_for_job(str(job.job_id))
    assert len(logs) == 1
    assert "Migration job created" in logs[0].message
