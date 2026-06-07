"""
Module: test_go_engine_metadata_repositories.py
Purpose: Unit tests for Go engine metadata repositories.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("METADATA_DB_URL", "sqlite+aiosqlite:///:memory:")

from infrastructure.metadata_db.models import Base, MigrationJobRecord
from infrastructure.metadata_db.repositories.go_migration_job_queue_repository import (
    GoMigrationJobQueueRepository,
)
from infrastructure.metadata_db.repositories.migration_job_log_repository import (
    MigrationJobLogRepository,
)
from infrastructure.metadata_db.repositories.migration_worker_heartbeat_repository import (
    MigrationWorkerHeartbeatRepository,
)


@pytest.fixture
async def session() -> AsyncSession:
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


def _job(job_id: str | None = None, status: str = "queued") -> MigrationJobRecord:
    return MigrationJobRecord(
        migration_job_id=job_id or str(uuid4()),
        status=status,
        executor="go",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_migration_job_log_repository_append_and_list(session: AsyncSession):
    job_id = str(uuid4())
    session.add(_job(job_id))
    await session.commit()

    repo = MigrationJobLogRepository(session)
    await repo.append(job_id, "dispatched to Go engine", level="info")
    logs = await repo.list_for_job(job_id)
    assert len(logs) == 1
    assert logs[0].message == "dispatched to Go engine"


@pytest.mark.asyncio
async def test_worker_heartbeat_recent(session: AsyncSession):
    repo = MigrationWorkerHeartbeatRepository(session)
    await repo.upsert("worker-a", status="idle")
    assert await repo.has_recent_heartbeat(within_seconds=60) is True


@pytest.mark.asyncio
async def test_go_job_queue_claim(session: AsyncSession):
    job_id = str(uuid4())
    session.add(_job(job_id, status="queued"))
    await session.commit()

    queue = GoMigrationJobQueueRepository(session)
    queued = await queue.list_queued_go_jobs()
    assert len(queued) == 1
    assert await queue.claim_job(job_id) is True
    assert await queue.claim_job(job_id) is False

    refreshed = await session.get(MigrationJobRecord, job_id)
    assert refreshed is not None
    assert refreshed.status == "running"
