"""Tests for metadata DB security audit (§12.8)."""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from application.metadata_security_service import MetadataSecurityService
from infrastructure.metadata_db.models import Base, ConnectionRecord
from infrastructure.metadata_db.repositories.connection_repository import ConnectionRepository


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
async def test_audit_flags_plaintext_password(session, monkeypatch):
    monkeypatch.setenv("MIGRATION_MASTER_KEY", "x" * 32)
    repo = ConnectionRepository(session)
    await repo.create(
        name="bad",
        db_type="sqlserver",
        host="h",
        port=1433,
        database_name="db",
        username="u",
        encrypted_password="plaintext-secret",
    )
    await session.commit()
    report = await MetadataSecurityService().audit(session)
    assert report.plaintext_credential_count == 1
    assert not report.to_dict()["compliant"]


@pytest.mark.asyncio
async def test_audit_accepts_fernet_ciphertext(session, monkeypatch):
    monkeypatch.setenv("MIGRATION_MASTER_KEY", "x" * 32)
    repo = ConnectionRepository(session)
    await repo.create(
        name="good",
        db_type="postgresql",
        host="h",
        port=5432,
        database_name="db",
        username="u",
        encrypted_password="c2FsdA==:gAAAAABfakefernettokenplaceholder",
    )
    await session.commit()
    report = await MetadataSecurityService().audit(session)
    assert report.plaintext_credential_count == 0
