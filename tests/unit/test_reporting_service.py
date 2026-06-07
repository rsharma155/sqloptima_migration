"""
Module: tests/unit/test_reporting_service.py
Purpose: Unit tests for ReportingService — migration summary, validation
         summary, and HTML rendering.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from application.reporting_service import ReportingService, ReportingServiceError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_job(job_id: str = "job-1") -> MagicMock:
    job = MagicMock()
    job.id = job_id
    job.status = "COMPLETED"
    job.tables_total = 3
    job.tables_done = 3
    job.rows_total = 30_000
    job.rows_migrated = 30_000
    job.started_at = datetime(2026, 5, 31, 10, 0, 0, tzinfo=UTC)
    job.completed_at = datetime(2026, 5, 31, 10, 5, 0, tzinfo=UTC)
    job.error = None
    plan = MagicMock()
    plan.schema_name = "dbo"
    plan.table_name = "orders"
    plan.status = "completed"
    plan.rows_migrated = 10_000
    plan.row_count_estimate = 10_000
    job.table_plans = [plan]
    return job


def _make_run(level: int = 1, fail: int = 0) -> MagicMock:
    run = MagicMock()
    run.validation_run_id = f"run-{level}"
    run.level = level
    run.status = "COMPLETED" if fail == 0 else "FAILED"
    run.pass_count = 5
    run.fail_count = fail
    run.started_at = datetime(2026, 5, 31, 10, 0, 0, tzinfo=UTC)
    run.completed_at = datetime(2026, 5, 31, 10, 1, 0, tzinfo=UTC)
    return run


def _make_service() -> ReportingService:
    session = MagicMock()
    svc = ReportingService(session)
    svc._job_repo = MagicMock()
    svc._val_repo = MagicMock()
    return svc


# ---------------------------------------------------------------------------
# migration_summary
# ---------------------------------------------------------------------------


class TestMigrationSummary:
    @pytest.mark.asyncio
    async def test_missing_job_raises(self):
        svc = _make_service()
        svc._job_repo.get_by_id = AsyncMock(return_value=None)
        with pytest.raises(ReportingServiceError, match="not found"):
            await svc.migration_summary("bad-id")

    @pytest.mark.asyncio
    async def test_summary_contains_expected_keys(self):
        svc = _make_service()
        svc._job_repo.get_by_id = AsyncMock(return_value=_make_job())
        result = await svc.migration_summary("job-1")
        assert result["report_type"] == "migration_summary"
        assert result["status"] == "COMPLETED"
        assert result["rows_migrated"] == 30_000
        assert "table_plans" in result
        assert len(result["table_plans"]) == 1

    @pytest.mark.asyncio
    async def test_summary_computes_duration(self):
        svc = _make_service()
        svc._job_repo.get_by_id = AsyncMock(return_value=_make_job())
        result = await svc.migration_summary("job-1")
        assert result["duration_seconds"] == pytest.approx(300.0)

    @pytest.mark.asyncio
    async def test_table_plan_pct_complete(self):
        svc = _make_service()
        svc._job_repo.get_by_id = AsyncMock(return_value=_make_job())
        result = await svc.migration_summary("job-1")
        assert result["table_plans"][0]["pct_complete"] == 100.0


# ---------------------------------------------------------------------------
# validation_summary
# ---------------------------------------------------------------------------


class TestValidationSummary:
    @pytest.mark.asyncio
    async def test_no_runs_raises(self):
        svc = _make_service()
        svc._val_repo.get_runs_for_job = AsyncMock(return_value=[])
        with pytest.raises(ReportingServiceError, match="No validation runs"):
            await svc.validation_summary("job-1")

    @pytest.mark.asyncio
    async def test_summary_contains_levels(self):
        svc = _make_service()
        svc._val_repo.get_runs_for_job = AsyncMock(
            return_value=[_make_run(1), _make_run(2)]
        )
        svc._val_repo.get_mismatches_for_run = AsyncMock(return_value=[])
        result = await svc.validation_summary("job-1")
        assert result["total_runs"] == 2
        assert len(result["levels"]) == 2

    @pytest.mark.asyncio
    async def test_overall_passed_when_no_failures(self):
        svc = _make_service()
        svc._val_repo.get_runs_for_job = AsyncMock(return_value=[_make_run(1, fail=0)])
        svc._val_repo.get_mismatches_for_run = AsyncMock(return_value=[])
        result = await svc.validation_summary("job-1")
        assert result["overall_passed"] is True

    @pytest.mark.asyncio
    async def test_overall_failed_when_any_run_fails(self):
        svc = _make_service()
        svc._val_repo.get_runs_for_job = AsyncMock(
            return_value=[_make_run(1, fail=0), _make_run(2, fail=3)]
        )
        svc._val_repo.get_mismatches_for_run = AsyncMock(return_value=[])
        result = await svc.validation_summary("job-1")
        assert result["overall_passed"] is False


# ---------------------------------------------------------------------------
# migration_summary_html
# ---------------------------------------------------------------------------


class TestMigrationSummaryHtml:
    def test_html_contains_doctype(self):
        summary = {
            "report_type": "migration_summary",
            "generated_at": "2026-05-31T10:00:00",
            "job_id": "job-1",
            "status": "COMPLETED",
            "rows_migrated": 10_000,
            "rows_total": 10_000,
            "table_plans": [],
        }
        html = ReportingService.migration_summary_html(summary)
        assert "<!DOCTYPE html>" in html

    def test_html_shows_job_id(self):
        summary = {
            "job_id": "job-abc",
            "status": "COMPLETED",
            "rows_migrated": 0,
            "rows_total": 0,
            "generated_at": "2026-05-31T10:00:00",
            "table_plans": [],
        }
        html = ReportingService.migration_summary_html(summary)
        assert "job-abc" in html

    def test_html_includes_table_rows(self):
        summary = {
            "job_id": "job-1",
            "status": "RUNNING",
            "rows_migrated": 500,
            "rows_total": 1000,
            "generated_at": "2026-05-31T10:00:00",
            "table_plans": [
                {"table": "dbo.orders", "status": "completed",
                 "rows_migrated": 500, "pct_complete": 50.0}
            ],
        }
        html = ReportingService.migration_summary_html(summary)
        assert "dbo.orders" in html
