"""Unit tests for infrastructure/metadata_db repositories.

All tests use an in-memory SQLite DB so they are self-contained,
require no external services, and run in < 1 s total.
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

# Point to in-memory SQLite before importing the session module
os.environ.setdefault("METADATA_DB_URL", "sqlite+aiosqlite:///:memory:")

from infrastructure.metadata_db.models import (
    Base,
    ConnectionRecord,
    MigrationCommandRecord,
    MigrationJobRecord,
    MigrationTablePlanRecord,
)
from infrastructure.metadata_db.repositories.connection_repository import ConnectionRepository
from infrastructure.metadata_db.repositories.job_repository import JobRepository
from infrastructure.metadata_db.repositories.command_repository import CommandRepository


# ---------------------------------------------------------------------------
# Shared async fixture: fresh in-memory DB per test
# ---------------------------------------------------------------------------

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


def _make_connection(cid: str | None = None, db_type: str = "postgresql") -> ConnectionRecord:
    return ConnectionRecord(
        project_connection_id=cid or str(uuid4()),
        name="test-conn",
        db_type=db_type,
        host="localhost",
        port=5432,
        database_name="mydb",
        username="user",
        encrypted_password="enc:abc",
        ssl_enabled=False,
        created_at=datetime.now(UTC),
    )


def _make_job(
    jid: str | None = None,
    src_id: str | None = None,
    tgt_id: str | None = None,
) -> MigrationJobRecord:
    return MigrationJobRecord(
        migration_job_id=jid or str(uuid4()),
        source_project_connection_id=src_id,
        target_project_connection_id=tgt_id,
        status="PENDING",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# ConnectionRepository
# ---------------------------------------------------------------------------

class TestConnectionRepository:
    async def test_upsert_and_get_by_id(self, session: AsyncSession):
        repo = ConnectionRepository(session)
        conn = _make_connection()
        await repo.upsert(conn)

        fetched = await repo.get_by_id(conn.project_connection_id)
        assert fetched is not None
        assert fetched.host == "localhost"
        assert fetched.db_type == "postgresql"

    async def test_get_all_returns_all_connections(self, session: AsyncSession):
        repo = ConnectionRepository(session)
        for _ in range(3):
            await repo.upsert(_make_connection())

        all_conns = await repo.get_all()
        assert len(all_conns) == 3

    async def test_upsert_updates_existing(self, session: AsyncSession):
        repo = ConnectionRepository(session)
        conn = _make_connection()
        await repo.upsert(conn)

        conn.host = "new-host"
        await repo.upsert(conn)

        fetched = await repo.get_by_id(conn.project_connection_id)
        assert fetched is not None
        assert fetched.host == "new-host"

    async def test_delete_removes_connection(self, session: AsyncSession):
        repo = ConnectionRepository(session)
        conn = _make_connection()
        await repo.upsert(conn)

        deleted = await repo.delete(conn.project_connection_id)
        assert deleted is True
        assert await repo.get_by_id(conn.project_connection_id) is None

    async def test_delete_nonexistent_returns_false(self, session: AsyncSession):
        repo = ConnectionRepository(session)
        assert await repo.delete("nonexistent-id") is False

    async def test_update_test_status_ok(self, session: AsyncSession):
        repo = ConnectionRepository(session)
        conn = _make_connection()
        await repo.upsert(conn)

        await repo.update_test_status(conn.project_connection_id, ok=True)

        fetched = await repo.get_by_id(conn.project_connection_id)
        assert fetched is not None
        assert fetched.last_test_ok is True
        assert fetched.last_tested_at is not None

    async def test_update_test_status_fail(self, session: AsyncSession):
        repo = ConnectionRepository(session)
        conn = _make_connection()
        await repo.upsert(conn)

        await repo.update_test_status(conn.project_connection_id, ok=False)

        fetched = await repo.get_by_id(conn.project_connection_id)
        assert fetched is not None
        assert fetched.last_test_ok is False

    async def test_encrypted_password_roundtrip(self, session: AsyncSession):
        repo = ConnectionRepository(session)
        conn = _make_connection()
        conn.encrypted_password = "salt:encryptedblob"
        await repo.upsert(conn)

        fetched = await repo.get_by_id(conn.project_connection_id)
        assert fetched is not None
        assert fetched.encrypted_password == "salt:encryptedblob"


# ---------------------------------------------------------------------------
# JobRepository
# ---------------------------------------------------------------------------

class TestJobRepository:
    async def test_upsert_and_get_by_id(self, session: AsyncSession):
        repo = JobRepository(session)
        job = _make_job()
        await repo.upsert(job)

        fetched = await repo.get_by_id(job.migration_job_id)
        assert fetched is not None
        assert fetched.status == "PENDING"

    async def test_get_all_returns_all_jobs(self, session: AsyncSession):
        repo = JobRepository(session)
        for _ in range(4):
            await repo.upsert(_make_job())

        all_jobs = await repo.get_all()
        assert len(all_jobs) == 4

    async def test_update_status(self, session: AsyncSession):
        repo = JobRepository(session)
        job = _make_job()
        await repo.upsert(job)

        await repo.update_status(job.migration_job_id, "RUNNING")

        fetched = await repo.get_by_id(job.migration_job_id)
        assert fetched is not None
        assert fetched.status == "RUNNING"

    async def test_completed_status_sets_completed_at(self, session: AsyncSession):
        repo = JobRepository(session)
        job = _make_job()
        await repo.upsert(job)

        await repo.update_status(job.migration_job_id, "COMPLETED")

        fetched = await repo.get_by_id(job.migration_job_id)
        assert fetched is not None
        assert fetched.completed_at is not None

    async def test_job_survives_upsert_round_trip(self, session: AsyncSession):
        """Simulates API restart: upsert a job, get it back, verify fields."""
        repo = JobRepository(session)
        jid = str(uuid4())
        job = _make_job(jid=jid)
        job.rows_migrated = 50_000
        job.tables_total = 5
        job.tables_done = 2
        await repo.upsert(job)

        fetched = await repo.get_by_id(jid)
        assert fetched is not None
        assert fetched.rows_migrated == 50_000
        assert fetched.tables_total == 5
        assert fetched.tables_done == 2

    async def test_table_plans_cascade_with_job(self, session: AsyncSession):
        repo = JobRepository(session)
        job = _make_job()
        plan = MigrationTablePlanRecord(
            migration_job_id=job.migration_job_id,
            table_name="orders",
            schema_name="dbo",
            strategy="chunked",
            chunk_size=10000,
            parallel_workers=4,
            status="pending",
        )
        job.table_plans = [plan]
        await repo.upsert(job)

        fetched = await repo.get_by_id(job.migration_job_id)
        assert fetched is not None
        assert len(fetched.table_plans) == 1
        assert fetched.table_plans[0].table_name == "orders"

    async def test_update_progress(self, session: AsyncSession):
        repo = JobRepository(session)
        job = _make_job()
        await repo.upsert(job)

        await repo.update_progress(job.migration_job_id, rows_migrated=12345, tables_done=3)

        fetched = await repo.get_by_id(job.migration_job_id)
        assert fetched is not None
        assert fetched.rows_migrated == 12345
        assert fetched.tables_done == 3


# ---------------------------------------------------------------------------
# CommandRepository
# ---------------------------------------------------------------------------

class TestCommandRepository:
    async def test_issue_and_get_command(self, session: AsyncSession):
        # Need a job first (FK constraint)
        job_repo = JobRepository(session)
        job = _make_job()
        await job_repo.upsert(job)

        cmd_repo = CommandRepository(session)
        await cmd_repo.issue(job.migration_job_id, "PAUSE")

        cmd = await cmd_repo.get_command(job.migration_job_id)
        assert cmd is not None
        assert cmd.command == "PAUSE"
        assert cmd.acked_at is None

    async def test_issue_upserts_existing_command(self, session: AsyncSession):
        job_repo = JobRepository(session)
        job = _make_job()
        await job_repo.upsert(job)

        cmd_repo = CommandRepository(session)
        await cmd_repo.issue(job.migration_job_id, "PAUSE")
        await cmd_repo.issue(job.migration_job_id, "STOP")  # overwrites PAUSE

        cmd = await cmd_repo.get_command(job.migration_job_id)
        assert cmd is not None
        assert cmd.command == "STOP"

    async def test_acknowledge_sets_acked_at(self, session: AsyncSession):
        job_repo = JobRepository(session)
        job = _make_job()
        await job_repo.upsert(job)

        cmd_repo = CommandRepository(session)
        await cmd_repo.issue(job.migration_job_id, "RESUME")
        await cmd_repo.acknowledge(job.migration_job_id)

        cmd = await cmd_repo.get_command(job.migration_job_id)
        assert cmd is not None
        assert cmd.acked_at is not None

    async def test_clear_removes_command(self, session: AsyncSession):
        job_repo = JobRepository(session)
        job = _make_job()
        await job_repo.upsert(job)

        cmd_repo = CommandRepository(session)
        await cmd_repo.issue(job.migration_job_id, "STOP")
        await cmd_repo.clear(job.migration_job_id)

        assert await cmd_repo.get_command(job.migration_job_id) is None

    async def test_get_command_returns_none_when_absent(self, session: AsyncSession):
        cmd_repo = CommandRepository(session)
        assert await cmd_repo.get_command("no-such-job") is None
