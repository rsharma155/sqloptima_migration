"""Unit tests for audit log persistence and token denylist."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from application.audit_service import AuditService
from infrastructure.metadata_db.models import Base
from shared.security.audit_log import AuditAction


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
async def test_audit_record_and_query(session: AsyncSession):
    svc = AuditService(session)
    await svc.record(
        AuditAction.MIGRATION_STARTED,
        actor="admin",
        resource="migration/job-1",
        details={"tables": ["users"]},
    )
    entries = await svc.query(action=AuditAction.MIGRATION_STARTED)
    assert len(entries) == 1
    assert entries[0].actor == "admin"
    assert entries[0].resource == "migration/job-1"


@pytest.mark.asyncio
async def test_token_denylist(session: AsyncSession):
    svc = AuditService(session)
    expires = datetime.now(UTC) + timedelta(hours=1)
    await svc.revoke_access_token("jti-abc", expires)
    assert await svc.is_token_revoked("jti-abc") is True
    assert await svc.is_token_revoked("jti-other") is False
