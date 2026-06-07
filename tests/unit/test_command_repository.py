"""Tests for migration command repository NOTIFY wiring."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from infrastructure.metadata_db.models import Base, MigrationCommandRecord, MigrationJobRecord
from infrastructure.metadata_db.repositories.command_repository import CommandRepository


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        sess.add(
            MigrationJobRecord(
                migration_job_id="job-1",
                status="running",
            )
        )
        await sess.commit()
        yield sess
    await engine.dispose()


@pytest.mark.asyncio
async def test_issue_command_resets_ack(session: AsyncSession) -> None:
    repo = CommandRepository(session)
    first = await repo.issue("job-1", "PAUSE")
    await repo.acknowledge("job-1")

    second = await repo.issue("job-1", "RESUME")
    assert second.command == "RESUME"
    assert second.acked_at is None

    row = await session.get(MigrationCommandRecord, "job-1")
    assert row is not None
    assert row.acked_at is None


@pytest.mark.asyncio
async def test_notify_worker_executes_without_error(session: AsyncSession) -> None:
    """SQLite lacks pg_notify; ensure the helper degrades gracefully in tests."""
    repo = CommandRepository(session)
    await repo.issue("job-1", "STOP")
    # On PostgreSQL this executes pg_notify; on SQLite the execute may no-op or fail.
    # We only assert the command row persisted.
    row = await session.get(MigrationCommandRecord, "job-1")
    assert row is not None
    assert row.command == "STOP"
