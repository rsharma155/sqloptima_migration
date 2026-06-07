# Author: Ravi Sharma
# Copyright (c) 2026 Ravi Sharma
# SPDX-License-Identifier: MIT

"""Unit tests for JobRepository — SQLite-backed persistent store for MigrationJob.

All tests use an in-memory SQLite database so they are fast and hermetic.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from application.job_repository import JobRepository
from domains.migration.migration_engine import (
    MigrationJob,
    MigrationStatus,
    MigrationStrategy,
    TableMigrationPlan,
)


def _make_job(
    status: MigrationStatus = MigrationStatus.PENDING,
    tables: list[str] | None = None,
) -> MigrationJob:
    """Create a minimal MigrationJob for testing."""
    tables = tables or ["orders"]
    return MigrationJob(
        source_connection_id=uuid4(),
        target_connection_id=uuid4(),
        status=status,
        tables=[
            TableMigrationPlan(
                table_name=t,
                schema_name="dbo",
                columns=["*"],
                row_count_estimate=0,
                strategy=MigrationStrategy.CHUNKED,
            )
            for t in tables
        ],
    )


@pytest.fixture
async def repo() -> JobRepository:
    """Return an initialised in-memory JobRepository."""
    r = JobRepository(db_path=":memory:")
    await r.initialize()
    return r


class TestJobRepositoryCreate:
    @pytest.mark.asyncio
    async def test_create_and_get_round_trips(self, repo: JobRepository) -> None:
        job = _make_job()
        await repo.create(job)
        loaded = await repo.get(str(job.job_id))
        assert loaded is not None
        assert loaded.job_id == job.job_id
        assert loaded.status == job.status

    @pytest.mark.asyncio
    async def test_get_missing_returns_none(self, repo: JobRepository) -> None:
        result = await repo.get(str(uuid4()))
        assert result is None

    @pytest.mark.asyncio
    async def test_create_persists_tables(self, repo: JobRepository) -> None:
        job = _make_job(tables=["customers", "orders"])
        await repo.create(job)
        loaded = await repo.get(str(job.job_id))
        assert loaded is not None
        table_names = {t.table_name for t in loaded.tables}
        assert table_names == {"customers", "orders"}

    @pytest.mark.asyncio
    async def test_create_persists_error_message(self, repo: JobRepository) -> None:
        job = _make_job(status=MigrationStatus.FAILED)
        job.error_message = "Connection refused"
        await repo.create(job)
        loaded = await repo.get(str(job.job_id))
        assert loaded is not None
        assert loaded.error_message == "Connection refused"


class TestJobRepositoryUpdateStatus:
    @pytest.mark.asyncio
    async def test_update_status_changes_status(self, repo: JobRepository) -> None:
        job = _make_job(status=MigrationStatus.PENDING)
        await repo.create(job)
        await repo.update_status(str(job.job_id), MigrationStatus.RUNNING)
        loaded = await repo.get(str(job.job_id))
        assert loaded is not None
        assert loaded.status == MigrationStatus.RUNNING

    @pytest.mark.asyncio
    async def test_update_status_sets_error(self, repo: JobRepository) -> None:
        job = _make_job()
        await repo.create(job)
        await repo.update_status(
            str(job.job_id), MigrationStatus.FAILED, error="Timeout"
        )
        loaded = await repo.get(str(job.job_id))
        assert loaded is not None
        assert loaded.status == MigrationStatus.FAILED
        assert loaded.error_message == "Timeout"

    @pytest.mark.asyncio
    async def test_update_status_missing_job_is_noop(self, repo: JobRepository) -> None:
        # Must not raise; updating a non-existent job_id is silently ignored.
        await repo.update_status(str(uuid4()), MigrationStatus.COMPLETED)


class TestJobRepositoryListAll:
    @pytest.mark.asyncio
    async def test_list_all_empty(self, repo: JobRepository) -> None:
        result = await repo.list_all()
        assert result == []

    @pytest.mark.asyncio
    async def test_list_all_returns_all_jobs(self, repo: JobRepository) -> None:
        job_a = _make_job(status=MigrationStatus.PENDING)
        job_b = _make_job(status=MigrationStatus.COMPLETED)
        await repo.create(job_a)
        await repo.create(job_b)
        result = await repo.list_all()
        ids = {j.job_id for j in result}
        assert job_a.job_id in ids
        assert job_b.job_id in ids

    @pytest.mark.asyncio
    async def test_list_all_reflects_status_update(self, repo: JobRepository) -> None:
        job = _make_job(status=MigrationStatus.PENDING)
        await repo.create(job)
        await repo.update_status(str(job.job_id), MigrationStatus.RUNNING)
        result = await repo.list_all()
        assert len(result) == 1
        assert result[0].status == MigrationStatus.RUNNING


class TestJobRepositoryDelete:
    @pytest.mark.asyncio
    async def test_delete_removes_job(self, repo: JobRepository) -> None:
        job = _make_job()
        await repo.create(job)
        await repo.delete(str(job.job_id))
        assert await repo.get(str(job.job_id)) is None

    @pytest.mark.asyncio
    async def test_delete_missing_is_noop(self, repo: JobRepository) -> None:
        # Must not raise.
        await repo.delete(str(uuid4()))

    @pytest.mark.asyncio
    async def test_delete_does_not_affect_other_jobs(self, repo: JobRepository) -> None:
        job_a = _make_job()
        job_b = _make_job()
        await repo.create(job_a)
        await repo.create(job_b)
        await repo.delete(str(job_a.job_id))
        assert await repo.get(str(job_b.job_id)) is not None
