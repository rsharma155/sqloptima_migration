# Author: Ravi Sharma
# Copyright (c) 2026 Ravi Sharma
# SPDX-License-Identifier: MIT

"""JobRegistry — the concurrency-safe in-process store for migration jobs.

Single responsibility: own the hot-path caches (`jobs` and their background
`asyncio.Task`s) and the synchronisation primitive that guards compound
read-modify-write sequences spanning ``await`` boundaries (Issue #1).

Why this exists as its own module:
    * Keeps `migration_service` an orchestrator rather than a god-module that
      also hand-rolls its own state container — a micro-architecture boundary.
    * Makes the concurrency contract independently unit-testable without the
      DB, connectors, or FastAPI in the loop.

Concurrency contract:
    * Single-key operations (``put``/``get``/``discard``/task ops) are atomic on
      a single asyncio event loop — they perform no ``await`` so no other
      coroutine can interleave mid-operation.
    * Any operation that *iterates* the job set must do so over :meth:`snapshot`,
      which copies under :attr:`lock`. This is what prevents a concurrent
      mutation from raising ``RuntimeError: dictionary changed size during
      iteration`` while another coroutine persists jobs.
    * Compound mutate-then-persist sequences in callers should be wrapped in
      ``async with registry.lock:`` to serialise them.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from domains.migration.migration_engine import MigrationJob


class JobRegistry:
    """In-process registry of migration jobs and their background tasks."""

    def __init__(self) -> None:
        self._jobs: dict[UUID, MigrationJob] = {}
        self._active_tasks: dict[UUID, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Synchronisation
    # ------------------------------------------------------------------

    @property
    def lock(self) -> asyncio.Lock:
        """Lock guarding compound read-modify-write sequences across awaits."""
        return self._lock

    async def snapshot(self) -> list[tuple[UUID, MigrationJob]]:
        """Return a lock-protected copy of all (job_id, job) pairs.

        Callers iterate this copy so concurrent mutation cannot corrupt the
        iteration.
        """
        async with self._lock:
            return list(self._jobs.items())

    # ------------------------------------------------------------------
    # Job state (single-key, event-loop-atomic operations)
    # ------------------------------------------------------------------

    def get(self, job_id: UUID) -> MigrationJob | None:
        return self._jobs.get(job_id)

    def contains(self, job_id: UUID) -> bool:
        return job_id in self._jobs

    def put(self, job: MigrationJob) -> None:
        self._jobs[job.job_id] = job

    def discard(self, job_id: UUID) -> None:
        self._jobs.pop(job_id, None)

    def all_items(self) -> list[tuple[UUID, MigrationJob]]:
        """Return a shallow snapshot copy of all (job_id, job) pairs.

        Synchronous variant for read-only callers (e.g. list endpoints) that do
        not need the lock; the returned list is decoupled from the live dict.
        """
        return list(self._jobs.items())

    def count(self) -> int:
        return len(self._jobs)

    def clear(self) -> None:
        self._jobs.clear()

    # ------------------------------------------------------------------
    # Background tasks
    # ------------------------------------------------------------------

    def set_task(self, job_id: UUID, task: asyncio.Task) -> None:
        self._active_tasks[job_id] = task

    def pop_task(self, job_id: UUID) -> asyncio.Task | None:
        return self._active_tasks.pop(job_id, None)

    def active_tasks(self) -> list[asyncio.Task]:
        """Return tasks that have not yet completed."""
        return [t for t in self._active_tasks.values() if not t.done()]
