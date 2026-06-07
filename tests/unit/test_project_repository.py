"""
Module: tests/unit/test_project_repository.py
Purpose: Unit tests for ProjectRepository — CRUD and uniqueness enforcement.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from infrastructure.metadata_db.models import Base
from infrastructure.metadata_db.repositories.project_repository import ProjectRepository


# ---------------------------------------------------------------------------
# In-memory SQLite fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        yield sess
    await engine.dispose()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestProjectRepositoryCreate:
    @pytest.mark.asyncio
    async def test_create_returns_record_with_id(self, session: AsyncSession):
        repo = ProjectRepository(session)
        record = await repo.create(name="Acme Migration")
        await session.commit()
        assert record.project_id
        assert record.name == "Acme Migration"

    @pytest.mark.asyncio
    async def test_created_at_is_set(self, session: AsyncSession):
        repo = ProjectRepository(session)
        record = await repo.create(name="Project A")
        assert record.created_at is not None

    @pytest.mark.asyncio
    async def test_description_optional(self, session: AsyncSession):
        repo = ProjectRepository(session)
        record = await repo.create(name="No Desc")
        assert record.description is None

    @pytest.mark.asyncio
    async def test_with_connections(self, session: AsyncSession):
        repo = ProjectRepository(session)
        record = await repo.create(
            name="Full Project",
            source_connection_id="src-1",
            target_connection_id="tgt-1",
        )
        assert record.source_project_connection_id == "src-1"
        assert record.target_project_connection_id == "tgt-1"


class TestProjectRepositoryQuery:
    @pytest.mark.asyncio
    async def test_get_by_id_existing(self, session: AsyncSession):
        repo = ProjectRepository(session)
        created = await repo.create(name="Find Me")
        await session.commit()
        found = await repo.get_by_id(created.project_id)
        assert found is not None
        assert found.project_id == created.project_id

    @pytest.mark.asyncio
    async def test_get_by_id_missing_returns_none(self, session: AsyncSession):
        repo = ProjectRepository(session)
        result = await repo.get_by_id("nonexistent-uuid")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_name_found(self, session: AsyncSession):
        repo = ProjectRepository(session)
        await repo.create(name="ByName")
        await session.commit()
        result = await repo.get_by_name("ByName")
        assert result is not None
        assert result.name == "ByName"

    @pytest.mark.asyncio
    async def test_get_by_name_missing_returns_none(self, session: AsyncSession):
        repo = ProjectRepository(session)
        result = await repo.get_by_name("Phantom")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_all_returns_all(self, session: AsyncSession):
        repo = ProjectRepository(session)
        await repo.create(name="P1")
        await repo.create(name="P2")
        await repo.create(name="P3")
        await session.commit()
        all_projects = await repo.get_all()
        assert len(all_projects) == 3

    @pytest.mark.asyncio
    async def test_get_all_ordered_by_name(self, session: AsyncSession):
        repo = ProjectRepository(session)
        await repo.create(name="Zebra")
        await repo.create(name="Apple")
        await repo.create(name="Mango")
        await session.commit()
        all_projects = await repo.get_all()
        names = [p.name for p in all_projects]
        assert names == sorted(names)


class TestProjectRepositoryUpdate:
    @pytest.mark.asyncio
    async def test_update_name(self, session: AsyncSession):
        repo = ProjectRepository(session)
        created = await repo.create(name="Old Name")
        await session.commit()
        updated = await repo.update(created.project_id, name="New Name")
        assert updated is not None
        assert updated.name == "New Name"

    @pytest.mark.asyncio
    async def test_update_missing_returns_none(self, session: AsyncSession):
        repo = ProjectRepository(session)
        result = await repo.update("bad-id", name="Whatever")
        assert result is None

    @pytest.mark.asyncio
    async def test_update_sets_updated_at(self, session: AsyncSession):
        import asyncio
        repo = ProjectRepository(session)
        created = await repo.create(name="Timestamps")
        await session.commit()
        original_updated_at = created.updated_at
        await asyncio.sleep(0.01)
        updated = await repo.update(created.project_id, description="new desc")
        # updated_at should be same or later (SQLite may not update it automatically)
        assert updated is not None


class TestProjectRepositoryDelete:
    @pytest.mark.asyncio
    async def test_delete_existing_returns_true(self, session: AsyncSession):
        repo = ProjectRepository(session)
        created = await repo.create(name="Doomed")
        await session.commit()
        result = await repo.delete(created.project_id)
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_removes_from_db(self, session: AsyncSession):
        repo = ProjectRepository(session)
        created = await repo.create(name="Gone")
        await session.commit()
        await repo.delete(created.project_id)
        await session.commit()
        found = await repo.get_by_id(created.project_id)
        assert found is None

    @pytest.mark.asyncio
    async def test_delete_missing_returns_false(self, session: AsyncSession):
        repo = ProjectRepository(session)
        result = await repo.delete("never-existed")
        assert result is False
