"""Unit tests for cutover checkpoint persistence and rollback (§13.2)."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from domains.orchestration.cutover_service import CutoverCheckpoint, CutoverService
from infrastructure.metadata_db.models import Base


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        yield sess
    await engine.dispose()


@pytest.mark.asyncio
async def test_save_and_rollback_checkpoint(session: AsyncSession):
    target = AsyncMock()
    target.execute = AsyncMock(return_value=[])

    svc = CutoverService(session, target_connector=target)
    await svc.save_checkpoint(
        CutoverCheckpoint(
            job_id="job-1",
            tables=["users", "orders"],
            target_schema="public",
        )
    )
    result = await svc.rollback("job-1")
    assert result["success"] is True
    assert set(result["tables_truncated"]) == {"users", "orders"}
    assert target.execute.call_count == 2


@pytest.mark.asyncio
async def test_rollback_blocked_after_commit(session: AsyncSession):
    svc = CutoverService(session)
    await svc.save_checkpoint(CutoverCheckpoint(job_id="job-2", tables=["users"]))
    await svc.mark_committed("job-2")
    result = await svc.rollback("job-2")
    assert result["success"] is False
    assert "committed" in result["error"].lower()
