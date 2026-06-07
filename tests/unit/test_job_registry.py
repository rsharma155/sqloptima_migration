"""
Module: tests/unit/test_job_registry.py
Purpose: Unit tests for JobRegistry — the concurrency-safe in-process store for
         migration jobs and their background tasks (Issue #1).
Domain: Application
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from application.job_registry import JobRegistry


class _FakeJob:
    """Minimal duck-typed stand-in for MigrationJob (needs only ``job_id``)."""

    def __init__(self) -> None:
        self.job_id = uuid4()


class _FakeTask:
    def __init__(self, done: bool = False) -> None:
        self._done = done

    def done(self) -> bool:
        return self._done


class TestJobRegistryState:
    def test_put_and_get(self) -> None:
        reg = JobRegistry()
        job = _FakeJob()
        reg.put(job)
        assert reg.get(job.job_id) is job

    def test_get_missing_returns_none(self) -> None:
        assert JobRegistry().get(uuid4()) is None

    def test_contains(self) -> None:
        reg = JobRegistry()
        job = _FakeJob()
        assert reg.contains(job.job_id) is False
        reg.put(job)
        assert reg.contains(job.job_id) is True

    def test_discard(self) -> None:
        reg = JobRegistry()
        job = _FakeJob()
        reg.put(job)
        reg.discard(job.job_id)
        assert reg.get(job.job_id) is None
        # Discarding a missing id is a no-op (no KeyError).
        reg.discard(uuid4())

    def test_count_and_clear(self) -> None:
        reg = JobRegistry()
        for _ in range(3):
            reg.put(_FakeJob())
        assert reg.count() == 3
        reg.clear()
        assert reg.count() == 0

    def test_all_items_is_decoupled_snapshot(self) -> None:
        reg = JobRegistry()
        job = _FakeJob()
        reg.put(job)
        items = reg.all_items()
        # Mutating the registry after taking the list must not change the list.
        reg.put(_FakeJob())
        assert len(items) == 1


class TestJobRegistryTasks:
    def test_task_set_pop(self) -> None:
        reg = JobRegistry()
        jid = uuid4()
        task = _FakeTask()
        reg.set_task(jid, task)
        assert reg.pop_task(jid) is task
        assert reg.pop_task(jid) is None

    def test_active_tasks_excludes_done(self) -> None:
        reg = JobRegistry()
        running = _FakeTask(done=False)
        finished = _FakeTask(done=True)
        reg.set_task(uuid4(), running)
        reg.set_task(uuid4(), finished)
        active = reg.active_tasks()
        assert running in active
        assert finished not in active


class TestJobRegistryConcurrency:
    def test_exposes_asyncio_lock(self) -> None:
        assert isinstance(JobRegistry().lock, asyncio.Lock)

    @pytest.mark.asyncio
    async def test_snapshot_acquires_lock_and_copies(self) -> None:
        reg = JobRegistry()
        for _ in range(5):
            reg.put(_FakeJob())
        snap = await reg.snapshot()
        assert len(snap) == 5
        reg.clear()
        # Snapshot is a copy — unaffected by later clear().
        assert len(snap) == 5

    @pytest.mark.asyncio
    async def test_snapshot_safe_under_concurrent_mutation(self) -> None:
        """Iterating a snapshot must never raise 'dict changed size during
        iteration' even while other coroutines add/remove jobs."""
        reg = JobRegistry()
        for _ in range(50):
            reg.put(_FakeJob())

        async def churn() -> None:
            for _ in range(200):
                j = _FakeJob()
                reg.put(j)
                reg.discard(j.job_id)
                await asyncio.sleep(0)

        async def reader() -> None:
            for _ in range(200):
                snap = await reg.snapshot()
                # Touch every item to force full iteration.
                _ = [jid for jid, _job in snap]
                await asyncio.sleep(0)

        await asyncio.gather(churn(), reader(), churn())
