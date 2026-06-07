"""
Module: tests/unit/test_validation_service.py
Purpose: Unit tests for ValidationService — orchestration of L1-L4 levels,
         persistence to validation_runs, and report export.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from application.validation_service import ValidationService, ValidationServiceError
from domains.validation.validation_engine import (
    ValidationCategory,
    ValidationResult,
    ValidationStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_passed_result(name: str = "dbo.orders") -> ValidationResult:
    return ValidationResult(
        object_name=name,
        category=ValidationCategory.ROW_COUNT,
        status=ValidationStatus.PASSED,
        source_count=100,
        target_count=100,
    )


def _make_failed_result(name: str = "dbo.customers") -> ValidationResult:
    from domains.validation.validation_engine import ValidationIssue

    return ValidationResult(
        object_name=name,
        category=ValidationCategory.ROW_COUNT,
        status=ValidationStatus.FAILED,
        source_count=100,
        target_count=90,
        issues=[
            ValidationIssue(
                category=ValidationCategory.ROW_COUNT,
                severity="error",
                message="Row count mismatch: 100 vs 90",
                source_value=100,
                target_value=90,
            )
        ],
    )


def _make_mock_session() -> MagicMock:
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.flush = AsyncMock()
    session.add = MagicMock()
    return session


# ---------------------------------------------------------------------------
# ValidationService._build_report
# ---------------------------------------------------------------------------


class TestBuildReport:
    def test_all_passed_results_in_passed_report(self):
        results = [_make_passed_result("t1"), _make_passed_result("t2")]
        report = ValidationService._build_report(results)
        assert report.overall_status == ValidationStatus.PASSED
        assert report.passed == 2
        assert report.failed == 0

    def test_one_failed_result_makes_report_failed(self):
        results = [_make_passed_result(), _make_failed_result()]
        report = ValidationService._build_report(results)
        assert report.overall_status == ValidationStatus.FAILED
        assert report.passed == 1
        assert report.failed == 1

    def test_empty_results_returns_passed_report(self):
        report = ValidationService._build_report([])
        assert report.overall_status == ValidationStatus.PASSED
        assert report.total_objects == 0


# ---------------------------------------------------------------------------
# ValidationService._report_to_dict
# ---------------------------------------------------------------------------


class TestReportToDict:
    def test_dict_contains_overall_status(self):
        results = [_make_passed_result()]
        report = ValidationService._build_report(results)
        d = ValidationService._report_to_dict(report)
        assert d["overall_status"] == "passed"
        assert d["total_objects"] == 1

    def test_failed_result_issues_in_dict(self):
        results = [_make_failed_result()]
        report = ValidationService._build_report(results)
        d = ValidationService._report_to_dict(report)
        assert d["failed"] == 1
        assert d["results"][0]["issues"]


# ---------------------------------------------------------------------------
# ValidationService._run_to_report
# ---------------------------------------------------------------------------


class TestRunToReport:
    def test_reconstructs_passed_report(self):
        run = MagicMock()
        run.report = {
            "overall_status": "passed",
            "total_objects": 1,
            "passed": 1,
            "failed": 0,
            "warnings": 0,
            "results": [
                {
                    "object_name": "dbo.orders",
                    "category": "row_count",
                    "status": "passed",
                    "source_count": 100,
                    "target_count": 100,
                    "issues": [],
                }
            ],
        }
        report = ValidationService._run_to_report(run)
        assert report.passed == 1
        assert report.failed == 0
        assert report.overall_status == ValidationStatus.PASSED

    def test_empty_report_returns_empty_passed_report(self):
        run = MagicMock()
        run.report = None
        report = ValidationService._run_to_report(run)
        assert report.total_objects == 0
        assert report.overall_status == ValidationStatus.PASSED

    def test_failed_run_report_reconstructed(self):
        run = MagicMock()
        run.report = {
            "overall_status": "failed",
            "total_objects": 2,
            "passed": 1,
            "failed": 1,
            "warnings": 0,
            "results": [
                {
                    "object_name": "dbo.t1",
                    "category": "row_count",
                    "status": "passed",
                    "source_count": 50,
                    "target_count": 50,
                    "issues": [],
                },
                {
                    "object_name": "dbo.t2",
                    "category": "row_count",
                    "status": "failed",
                    "source_count": 100,
                    "target_count": 90,
                    "issues": [{"severity": "error", "message": "mismatch"}],
                },
            ],
        }
        report = ValidationService._run_to_report(run)
        assert report.overall_status == ValidationStatus.FAILED
        assert report.failed == 1
        assert len(report.results) == 2


# ---------------------------------------------------------------------------
# ValidationService.get_report — format dispatch
# ---------------------------------------------------------------------------


class TestGetReport:
    @pytest.mark.asyncio
    async def test_unsupported_format_raises(self):
        session = _make_mock_session()
        svc = ValidationService(session)
        with pytest.raises(ValidationServiceError, match="Unsupported format"):
            await svc.get_report("run-123", "pdf")

    @pytest.mark.asyncio
    async def test_run_not_found_raises(self):
        session = _make_mock_session()
        svc = ValidationService(session)
        svc._repo = MagicMock()
        svc._repo.get_run = AsyncMock(return_value=None)
        with pytest.raises(ValidationServiceError, match="not found"):
            await svc.get_report("bad-id", "json")

    @pytest.mark.asyncio
    async def test_json_export_returns_string(self):
        run = MagicMock()
        run.report = {
            "overall_status": "passed",
            "total_objects": 0,
            "passed": 0,
            "failed": 0,
            "warnings": 0,
            "results": [],
        }
        session = _make_mock_session()
        svc = ValidationService(session)
        svc._repo = MagicMock()
        svc._repo.get_run = AsyncMock(return_value=run)
        content = await svc.get_report("run-123", "json")
        assert isinstance(content, str)
        import json
        parsed = json.loads(content)
        assert "overall_status" in parsed

    @pytest.mark.asyncio
    async def test_html_export_returns_html(self):
        run = MagicMock()
        run.report = {
            "overall_status": "passed",
            "total_objects": 0,
            "passed": 0,
            "failed": 0,
            "warnings": 0,
            "results": [],
        }
        session = _make_mock_session()
        svc = ValidationService(session)
        svc._repo = MagicMock()
        svc._repo.get_run = AsyncMock(return_value=run)
        content = await svc.get_report("run-123", "html")
        assert "<!DOCTYPE html>" in content
        assert "Migration Validation Report" in content

    @pytest.mark.asyncio
    async def test_csv_export_returns_csv(self):
        run = MagicMock()
        run.report = {
            "overall_status": "passed",
            "total_objects": 0,
            "passed": 0,
            "failed": 0,
            "warnings": 0,
            "results": [],
        }
        session = _make_mock_session()
        svc = ValidationService(session)
        svc._repo = MagicMock()
        svc._repo.get_run = AsyncMock(return_value=run)
        content = await svc.get_report("run-123", "csv")
        assert "object_name" in content  # CSV header row


# ---------------------------------------------------------------------------
# ValidationService.run_level — invalid level
# ---------------------------------------------------------------------------


class TestRunLevel:
    @pytest.mark.asyncio
    async def test_invalid_level_raises(self):
        session = _make_mock_session()
        svc = ValidationService(session)
        with pytest.raises(ValidationServiceError, match="Invalid level"):
            await svc.run_level(
                job_id="j1",
                level=5,
                source_connector=MagicMock(),
                target_connector=MagicMock(),
                tables=[],
            )
