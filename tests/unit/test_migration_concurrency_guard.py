# Author: Ravi Sharma
# Copyright (c) 2026 Ravi Sharma
# SPDX-License-Identifier: MIT

"""Unit tests for MigrationConcurrencyGuard.

Verifies that overlapping table conflicts are detected and non-overlapping
migrations are correctly allowed through.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from application.concurrency_guard import MigrationConcurrencyGuard
from domains.migration.migration_engine import (
    MigrationJob,
    MigrationStatus,
    MigrationStrategy,
    TableMigrationPlan,
)


def _make_running_job(table_names: list[str]) -> MigrationJob:
    """Build a running MigrationJob targeting the given tables."""
    return MigrationJob(
        source_connection_id=uuid4(),
        target_connection_id=uuid4(),
        status=MigrationStatus.RUNNING,
        tables=[
            TableMigrationPlan(
                table_name=t,
                schema_name="dbo",
                columns=["*"],
                row_count_estimate=0,
                strategy=MigrationStrategy.CHUNKED,
            )
            for t in table_names
        ],
    )


def _make_paused_job(table_names: list[str]) -> MigrationJob:
    return MigrationJob(
        source_connection_id=uuid4(),
        target_connection_id=uuid4(),
        status=MigrationStatus.PAUSED,
        tables=[
            TableMigrationPlan(
                table_name=t,
                schema_name="dbo",
                columns=["*"],
                row_count_estimate=0,
                strategy=MigrationStrategy.CHUNKED,
            )
            for t in table_names
        ],
    )


class TestMigrationConcurrencyGuardNoConflict:
    def test_no_running_jobs_allows_all(self) -> None:
        guard = MigrationConcurrencyGuard()
        conflict = guard.check_table_conflict(
            requested_tables=["users", "orders"],
            running_jobs=[],
        )
        assert conflict == set()

    def test_non_overlapping_tables_are_allowed(self) -> None:
        guard = MigrationConcurrencyGuard()
        running = _make_running_job(["customers", "products"])
        conflict = guard.check_table_conflict(
            requested_tables=["orders", "invoices"],
            running_jobs=[running],
        )
        assert conflict == set()

    def test_paused_job_does_not_block(self) -> None:
        """A PAUSED job must not count as a conflict — only RUNNING jobs do."""
        guard = MigrationConcurrencyGuard()
        paused = _make_paused_job(["orders"])
        conflict = guard.check_table_conflict(
            requested_tables=["orders"],
            running_jobs=[paused],
        )
        assert conflict == set()

    def test_completed_job_does_not_block(self) -> None:
        guard = MigrationConcurrencyGuard()
        done = MigrationJob(
            source_connection_id=uuid4(),
            target_connection_id=uuid4(),
            status=MigrationStatus.COMPLETED,
            tables=[
                TableMigrationPlan(
                    table_name="orders",
                    schema_name="dbo",
                    columns=["*"],
                    row_count_estimate=0,
                    strategy=MigrationStrategy.CHUNKED,
                )
            ],
        )
        conflict = guard.check_table_conflict(
            requested_tables=["orders"],
            running_jobs=[done],
        )
        assert conflict == set()


class TestMigrationConcurrencyGuardConflict:
    def test_single_overlapping_table_detected(self) -> None:
        guard = MigrationConcurrencyGuard()
        running = _make_running_job(["orders", "customers"])
        conflict = guard.check_table_conflict(
            requested_tables=["orders"],
            running_jobs=[running],
        )
        assert conflict == {"orders"}

    def test_multiple_overlapping_tables_detected(self) -> None:
        guard = MigrationConcurrencyGuard()
        running = _make_running_job(["orders", "customers", "products"])
        conflict = guard.check_table_conflict(
            requested_tables=["orders", "customers", "invoices"],
            running_jobs=[running],
        )
        assert conflict == {"orders", "customers"}

    def test_conflict_across_multiple_running_jobs(self) -> None:
        guard = MigrationConcurrencyGuard()
        running_a = _make_running_job(["orders"])
        running_b = _make_running_job(["customers"])
        conflict = guard.check_table_conflict(
            requested_tables=["orders", "customers", "products"],
            running_jobs=[running_a, running_b],
        )
        assert conflict == {"orders", "customers"}

    def test_exact_match_all_tables_conflict(self) -> None:
        guard = MigrationConcurrencyGuard()
        running = _make_running_job(["a", "b", "c"])
        conflict = guard.check_table_conflict(
            requested_tables=["a", "b", "c"],
            running_jobs=[running],
        )
        assert conflict == {"a", "b", "c"}

    def test_only_running_status_counts_as_conflict(self) -> None:
        """RUNNING jobs block; all other statuses are ignored."""
        guard = MigrationConcurrencyGuard()
        running = _make_running_job(["orders"])
        paused = _make_paused_job(["invoices"])
        conflict = guard.check_table_conflict(
            requested_tables=["orders", "invoices"],
            running_jobs=[running, paused],
        )
        # Only "orders" conflicts (from RUNNING job); "invoices" (PAUSED) does not.
        assert conflict == {"orders"}
