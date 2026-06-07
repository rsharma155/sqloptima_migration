"""
Module: application/concurrency_guard.py
Purpose: Fix 7.2 — stateless helper that checks whether a new migration request would
         conflict with any currently RUNNING job by overlapping on table names.
         Extracted from MigrationService into its own module so it can be tested
         independently and reused across API and CLI entry points.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from domains.migration.migration_engine import MigrationJob, MigrationStatus


class MigrationConcurrencyGuard:
    """Detects table-level conflicts between a new migration request and running jobs.

    Only jobs with status RUNNING are considered active conflicts.  PAUSED,
    COMPLETED, FAILED, and PENDING jobs are ignored so that pausing a job does
    not permanently lock its tables.
    """

    def check_table_conflict(
        self,
        requested_tables: list[str],
        running_jobs: list[MigrationJob],
    ) -> set[str]:
        """Return the set of table names that conflict with active (RUNNING) jobs.

        An empty set means no conflicts and the migration may proceed.
        """
        requested = set(requested_tables)
        active_tables: set[str] = set()
        for job in running_jobs:
            if job.status == MigrationStatus.RUNNING:
                for plan in job.tables:
                    active_tables.add(plan.table_name)
        return requested & active_tables
