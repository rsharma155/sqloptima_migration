"""Tests for migration program / wave repository (§13.1)."""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from infrastructure.metadata_db.models import Base, ProjectRecord
from infrastructure.metadata_db.repositories.migration_program_repository import (
    MigrationProgramRepository,
)


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        from datetime import UTC, datetime
        from uuid import uuid4

        now = datetime.now(UTC)
        project = ProjectRecord(
            project_id=str(uuid4()),
            name="Test Project",
            created_at=now,
            updated_at=now,
        )
        sess.add(project)
        await sess.flush()
        yield sess, project.project_id
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_program_and_wave(session):
    sess, project_id = session
    repo = MigrationProgramRepository(sess)
    program = await repo.create_program(project_id, "Wave Program", owner="dba@acme.com")
    wave = await repo.add_wave(program.migration_program_id, "Wave 1", ["users", "orders"])
    signed = await repo.sign_off_wave(wave.migration_wave_id, "cto@acme.com")
    assert signed is not None
    assert signed.status == "approved"
    await sess.commit()
    loaded = await repo.get_program(program.migration_program_id)
    assert loaded is not None
    assert len(loaded.waves) == 1
    assert loaded.waves[0].tables == ["users", "orders"]
