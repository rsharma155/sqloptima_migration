"""
Module: tests/unit/test_retention_policy.py
Purpose: Unit tests for RetentionPolicy domain logic and RetentionService
         application service (in-memory SQLite).
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from application.retention_service import RetentionResult, RetentionService
from domains.migration.retention_policy import RetentionAction, RetentionPolicy
from infrastructure.metadata_db.models import Base, MigrationJobRecord

# ---------------------------------------------------------------------------
# RetentionPolicy unit tests (pure domain logic)
# ---------------------------------------------------------------------------


class TestRetentionPolicy:
    def test_completed_job_older_than_window_is_eligible(self) -> None:
        policy = RetentionPolicy(max_age_days=30)
        assert policy.is_eligible_for_cleanup("COMPLETED", age_days=31) is True

    def test_completed_job_within_window_not_eligible(self) -> None:
        policy = RetentionPolicy(max_age_days=30)
        assert policy.is_eligible_for_cleanup("COMPLETED", age_days=29) is False

    def test_running_job_never_eligible_even_if_old(self) -> None:
        policy = RetentionPolicy(max_age_days=1)
        assert policy.is_eligible_for_cleanup("RUNNING", age_days=1000) is False
        assert policy.is_eligible_for_cleanup("PAUSED", age_days=1000) is False

    def test_failed_job_exempt_when_keep_failed_true(self) -> None:
        policy = RetentionPolicy(max_age_days=7, keep_failed=True)
        assert policy.is_eligible_for_cleanup("FAILED", age_days=100) is False

    def test_failed_job_eligible_when_keep_failed_false(self) -> None:
        policy = RetentionPolicy(max_age_days=7, keep_failed=False)
        assert policy.is_eligible_for_cleanup("FAILED", age_days=10) is True

    def test_exactly_at_boundary_is_eligible(self) -> None:
        policy = RetentionPolicy(max_age_days=30)
        assert policy.is_eligible_for_cleanup("COMPLETED", age_days=30) is True

    def test_retention_window_returns_timedelta(self) -> None:
        policy = RetentionPolicy(max_age_days=45)
        assert policy.retention_window == timedelta(days=45)

    def test_default_factory(self) -> None:
        policy = RetentionPolicy.default()
        assert policy.max_age_days == 90
        assert policy.action == RetentionAction.DELETE

    def test_aggressive_factory(self) -> None:
        policy = RetentionPolicy.aggressive()
        assert policy.max_age_days == 7

    def test_conservative_factory(self) -> None:
        policy = RetentionPolicy.conservative()
        assert policy.max_age_days == 365
        assert policy.keep_failed is True

    def test_policy_is_immutable(self) -> None:
        policy = RetentionPolicy.default()
        with pytest.raises((AttributeError, TypeError)):
            policy.max_age_days = 1  # type: ignore[misc]


# ---------------------------------------------------------------------------
# RetentionService integration tests (in-memory SQLite)
# ---------------------------------------------------------------------------


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as sess:
        yield sess
    await engine.dispose()


def _make_job(
    job_id: str,
    status: str,
    age_days: float,
) -> MigrationJobRecord:
    created = datetime.now(UTC) - timedelta(days=age_days)
    return MigrationJobRecord(
        migration_job_id=job_id,
        status=status,
        tables_total=1,
        tables_done=1,
        rows_total=100,
        rows_migrated=100,
        created_at=created,
    )


class TestRetentionService:
    @pytest.mark.asyncio
    async def test_old_completed_job_deleted(self, session: AsyncSession) -> None:
        job = _make_job("job-1", "COMPLETED", age_days=100)
        session.add(job)
        await session.flush()

        svc = RetentionService(session, RetentionPolicy(max_age_days=30))
        result = await svc.run(dry_run=False)

        await session.commit()
        assert result.deleted == 1
        assert result.scanned == 1

    @pytest.mark.asyncio
    async def test_young_completed_job_not_deleted(self, session: AsyncSession) -> None:
        job = _make_job("job-2", "COMPLETED", age_days=10)
        session.add(job)
        await session.flush()

        svc = RetentionService(session, RetentionPolicy(max_age_days=30))
        result = await svc.run(dry_run=False)

        await session.commit()
        assert result.deleted == 0
        assert result.skipped == 1

    @pytest.mark.asyncio
    async def test_running_job_always_skipped(self, session: AsyncSession) -> None:
        job = _make_job("job-3", "RUNNING", age_days=365)
        session.add(job)
        await session.flush()

        svc = RetentionService(session, RetentionPolicy(max_age_days=1))
        result = await svc.run(dry_run=False)

        await session.commit()
        assert result.deleted == 0
        assert result.skipped == 1

    @pytest.mark.asyncio
    async def test_dry_run_does_not_delete(self, session: AsyncSession) -> None:
        job = _make_job("job-4", "COMPLETED", age_days=100)
        session.add(job)
        await session.flush()

        svc = RetentionService(session, RetentionPolicy(max_age_days=30))
        result = await svc.run(dry_run=True)

        # dry_run: result.deleted shows would-delete count, but row still exists
        assert result.deleted == 1
        remaining = await session.get(MigrationJobRecord, "job-4")
        assert remaining is not None

    @pytest.mark.asyncio
    async def test_mixed_jobs_only_eligible_deleted(self, session: AsyncSession) -> None:
        session.add(_make_job("old-completed", "COMPLETED", age_days=100))
        session.add(_make_job("young-completed", "COMPLETED", age_days=5))
        session.add(_make_job("old-running", "RUNNING", age_days=200))
        session.add(_make_job("old-failed-keep", "FAILED", age_days=100))
        await session.flush()

        policy = RetentionPolicy(max_age_days=30, keep_failed=True)
        svc = RetentionService(session, policy)
        result = await svc.run(dry_run=False)

        await session.commit()
        assert result.deleted == 1  # only old-completed
        assert result.scanned == 4
        # Verify the right job was deleted
        assert await session.get(MigrationJobRecord, "old-completed") is None
        assert await session.get(MigrationJobRecord, "young-completed") is not None
        assert await session.get(MigrationJobRecord, "old-failed-keep") is not None

    @pytest.mark.asyncio
    async def test_empty_db_returns_zero_counts(self, session: AsyncSession) -> None:
        svc = RetentionService(session, RetentionPolicy.default())
        result = await svc.run()
        assert result.scanned == 0
        assert result.deleted == 0

    @pytest.mark.asyncio
    async def test_result_has_ran_at_timestamp(self, session: AsyncSession) -> None:
        svc = RetentionService(session, RetentionPolicy.default())
        result = await svc.run()
        assert isinstance(result, RetentionResult)
        assert result.ran_at  # non-empty ISO timestamp
