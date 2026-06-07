"""
Module: test_reporting_engine.py
Purpose: Unit tests for reporting engine
Author: Migration Platform Team
Created: 2026-05-22
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from unittest.mock import MagicMock

import pytest

from domains.reporting.reporting_engine import (
    AssessmentSection,
    MigrationReport,
    ObjectSummary,
    ReportFormat,
    ReportingEngine,
)


class TestObjectSummary:
    def test_create_summary(self):
        obj = ObjectSummary(
            name="users",
            object_type="table",
            schema_name="dbo",
            status="auto_convertible",
            issues=["Issue 1"],
        )
        assert obj.name == "users"
        assert len(obj.issues) == 1


class TestAssessmentSection:
    def test_create_section(self):
        section = AssessmentSection(
            title="Summary",
            content="Content here",
            metrics={"total": 10},
        )
        assert section.title == "Summary"
        assert section.metrics["total"] == 10


class TestMigrationReport:
    def test_create_report(self):
        report = MigrationReport(
            project_name="Test Migration",
            source_database="SQLServer01",
        )
        assert report.project_name == "Test Migration"
        assert report.target_database == "PostgreSQL"
        assert report.auto_convertible_percentage == 100.0

    def test_auto_generated_uuid(self):
        report = MigrationReport(project_name="P")
        assert report.report_id is not None


class TestReportingEngine:
    @pytest.fixture
    def engine(self):
        return ReportingEngine()

    def _make_mock_result(self, status: str, name: str = "obj", obj_type: str = "table"):
        r = MagicMock()
        r.status.value = status
        r.issues = []

        obj = MagicMock()
        obj.object_name = name
        obj.schema_name = "dbo"
        obj.object_type.value = obj_type
        obj.fully_qualified_name = f"dbo.{name}"

        r.object = obj
        return r

    def test_generate_report_basic(self, engine):
        results = [
            self._make_mock_result("auto_convertible", "users"),
            self._make_mock_result("partial", "usp_complex"),
            self._make_mock_result("unsupported", "clr_proc"),
        ]
        report = engine.generate_report("Test", "SQLServer01", results)
        assert report.total_objects == 3
        assert report.auto_convertible == 1
        assert report.partial == 1
        assert report.unsupported == 1

    def test_generate_report_percentage(self, engine):
        results = [
            self._make_mock_result("auto_convertible", "t1"),
            self._make_mock_result("auto_convertible", "t2"),
            self._make_mock_result("partial", "t3"),
        ]
        report = engine.generate_report("P", "DB", results)
        assert report.auto_convertible_percentage == 66.7

    def test_generate_report_empty(self, engine):
        report = engine.generate_report("Empty", "DB", [])
        assert report.total_objects == 0
        assert report.auto_convertible_percentage == 100.0

    def test_report_sections(self, engine):
        results = [self._make_mock_result("auto_convertible", "users")]
        report = engine.generate_report("Test", "DB", results)
        assert len(report.sections) >= 3

    def test_estimate_effort(self, engine):
        results = [
            self._make_mock_result("auto_convertible"),
            self._make_mock_result("partial"),
            self._make_mock_result("unsupported"),
        ]
        report = engine.generate_report("Test", "DB", results)
        assert report.estimated_effort_hours > 0

    def test_format_markdown(self, engine):
        results = [self._make_mock_result("auto_convertible", "users")]
        report = engine.generate_report("Test", "DB", results)
        md = engine.format_report(report, ReportFormat.MARKDOWN)
        assert "Migration Assessment Report" in md
        assert "Test" in md

    def test_format_json(self, engine):
        results = [self._make_mock_result("auto_convertible")]
        report = engine.generate_report("P", "DB", results)
        json_str = engine.format_report(report, ReportFormat.JSON)
        assert '"project_name"' in json_str
        assert '"total_objects"' in json_str

    def test_with_object_details(self, engine):
        results = [self._make_mock_result("partial", "usp_test", "procedure")]
        details = [
            {
                "name": "usp_test",
                "type": "procedure",
                "schema": "dbo",
                "status": "partial",
                "issues": ["Dynamic SQL detected"],
                "warnings": ["Manual review required"],
            }
        ]
        report = engine.generate_report("P", "DB", results, details)
        assert len(report.sections) >= 4

    def test_estimate_downtime(self, engine):
        results = [self._make_mock_result("auto_convertible") for _ in range(50)]
        report = engine.generate_report("P", "DB", results)
        assert report.estimated_downtime_minutes <= 480
        assert report.estimated_downtime_minutes > 0
