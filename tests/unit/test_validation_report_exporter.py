"""
Module: tests/unit/test_validation_report_exporter.py
Purpose: Unit tests for ValidationReportExporter — verifies JSON, CSV, and HTML
         output formats contain the required data.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import csv
import io
import json

import pytest

from domains.validation.validation_engine import (
    ValidationCategory,
    ValidationIssue,
    ValidationReport,
    ValidationResult,
    ValidationStatus,
)
from domains.validation.validation_report_exporter import ValidationReportExporter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _build_report(status: ValidationStatus = ValidationStatus.PASSED) -> ValidationReport:
    result1 = ValidationResult(
        object_name="dbo.orders",
        category=ValidationCategory.ROW_COUNT,
        status=ValidationStatus.PASSED,
        source_count=1000,
        target_count=1000,
    )
    result2 = ValidationResult(
        object_name="dbo.customers",
        category=ValidationCategory.CHECKSUM,
        status=ValidationStatus.FAILED,
        source_count=500,
        target_count=490,
        issues=[
            ValidationIssue(
                category=ValidationCategory.CHECKSUM,
                severity="error",
                message="Row count mismatch: source=500, target=490",
                source_value=500,
                target_value=490,
            )
        ],
    )
    report = ValidationReport(
        results=[result1, result2],
        total_objects=2,
        passed=1,
        failed=1,
        warnings=0,
        overall_status=status,
    )
    return report


# ---------------------------------------------------------------------------
# JSON export
# ---------------------------------------------------------------------------


class TestJsonExport:
    def test_json_is_valid(self):
        exporter = ValidationReportExporter()
        report = _build_report()
        json_str = exporter.to_json(report)
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)

    def test_json_contains_report_id(self):
        exporter = ValidationReportExporter()
        report = _build_report()
        parsed = json.loads(exporter.to_json(report))
        assert "report_id" in parsed

    def test_json_contains_results(self):
        exporter = ValidationReportExporter()
        report = _build_report()
        parsed = json.loads(exporter.to_json(report))
        assert len(parsed["results"]) == 2

    def test_json_summary_counts_correct(self):
        exporter = ValidationReportExporter()
        report = _build_report()
        parsed = json.loads(exporter.to_json(report))
        assert parsed["summary"]["passed"] == 1
        assert parsed["summary"]["failed"] == 1

    def test_json_overall_status_present(self):
        exporter = ValidationReportExporter()
        report = _build_report(ValidationStatus.FAILED)
        parsed = json.loads(exporter.to_json(report))
        assert parsed["overall_status"] == "failed"

    def test_json_issues_included(self):
        exporter = ValidationReportExporter()
        report = _build_report()
        parsed = json.loads(exporter.to_json(report))
        failed_result = next(r for r in parsed["results"] if r["status"] == "failed")
        assert len(failed_result["issues"]) == 1
        assert "Row count mismatch" in failed_result["issues"][0]["message"]

    def test_json_empty_report(self):
        exporter = ValidationReportExporter()
        report = ValidationReport()
        json_str = exporter.to_json(report)
        parsed = json.loads(json_str)
        assert parsed["summary"]["total_objects"] == 0


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------


class TestCsvExport:
    def test_csv_has_header_row(self):
        exporter = ValidationReportExporter()
        report = _build_report()
        csv_str = exporter.to_csv(report)
        reader = csv.reader(io.StringIO(csv_str))
        header = next(reader)
        assert "object_name" in header
        assert "status" in header
        assert "issues" in header

    def test_csv_row_count_matches_results(self):
        exporter = ValidationReportExporter()
        report = _build_report()
        csv_str = exporter.to_csv(report)
        rows = list(csv.reader(io.StringIO(csv_str)))
        # header + 2 results
        assert len(rows) == 3

    def test_csv_contains_object_names(self):
        exporter = ValidationReportExporter()
        report = _build_report()
        csv_str = exporter.to_csv(report)
        assert "dbo.orders" in csv_str
        assert "dbo.customers" in csv_str

    def test_csv_issues_in_last_column(self):
        exporter = ValidationReportExporter()
        report = _build_report()
        csv_str = exporter.to_csv(report)
        assert "Row count mismatch" in csv_str

    def test_csv_empty_report(self):
        exporter = ValidationReportExporter()
        report = ValidationReport()
        csv_str = exporter.to_csv(report)
        rows = list(csv.reader(io.StringIO(csv_str)))
        assert len(rows) == 1  # header only


# ---------------------------------------------------------------------------
# HTML export
# ---------------------------------------------------------------------------


class TestHtmlExport:
    def test_html_is_non_empty(self):
        exporter = ValidationReportExporter()
        report = _build_report()
        html_str = exporter.to_html(report)
        assert len(html_str) > 100

    def test_html_contains_doctype(self):
        exporter = ValidationReportExporter()
        html_str = exporter.to_html(_build_report())
        assert "<!DOCTYPE html>" in html_str

    def test_html_contains_object_names(self):
        exporter = ValidationReportExporter()
        html_str = exporter.to_html(_build_report())
        assert "dbo.orders" in html_str
        assert "dbo.customers" in html_str

    def test_html_overall_status_shown(self):
        exporter = ValidationReportExporter()
        html_str = exporter.to_html(_build_report(ValidationStatus.FAILED))
        assert "FAILED" in html_str

    def test_html_issue_message_escaped(self):
        exporter = ValidationReportExporter()
        result = ValidationResult(
            object_name="tbl",
            category=ValidationCategory.ROW_COUNT,
            status=ValidationStatus.FAILED,
            issues=[
                ValidationIssue(
                    category=ValidationCategory.ROW_COUNT,
                    severity="error",
                    message="<script>alert('xss')</script>",
                )
            ],
        )
        report = ValidationReport(results=[result], total_objects=1)
        html_str = exporter.to_html(report)
        # XSS payload must be escaped — no raw <script> tag
        assert "<script>alert" not in html_str
        assert "&lt;script&gt;" in html_str

    def test_html_summary_counts_visible(self):
        exporter = ValidationReportExporter()
        html_str = exporter.to_html(_build_report())
        assert ">1<" in html_str  # passed count

    def test_result_to_dict_serializes_decimal_aggregate_values(self):
        from decimal import Decimal

        from domains.validation.validation_report_exporter import result_to_dict

        result = ValidationResult(
            object_name="Purchasing.ProductVendor",
            category=ValidationCategory.AGGREGATE,
            status=ValidationStatus.PASSED,
            details={
                "column_results": [
                    {
                        "column": "StandardPrice",
                        "status": "passed",
                        "source": {
                            "min": Decimal("1.25"),
                            "max": Decimal("99.99"),
                            "sum": Decimal("1234.56"),
                            "avg": Decimal("12.345678"),
                        },
                        "target": {
                            "min": Decimal("1.25"),
                            "max": Decimal("99.99"),
                            "sum": Decimal("1234.56"),
                            "avg": Decimal("12.345678"),
                        },
                    }
                ],
            },
        )
        payload = result_to_dict(result)
        json.dumps(payload)
        col = payload["details"]["column_results"][0]
        assert col["source"]["min"] == 1.25
        assert col["target"]["sum"] == 1234.56

    def test_aggregate_html_shows_column_details(self):
        exporter = ValidationReportExporter()
        result = ValidationResult(
            object_name="dbo.orders",
            category=ValidationCategory.AGGREGATE,
            status=ValidationStatus.PASSED,
            details={
                "column_results": [
                    {
                        "column": "id",
                        "status": "passed",
                        "source": {"min": 1, "max": 10, "sum": 55, "avg": 5.5},
                        "target": {"min": 1, "max": 10, "sum": 55, "avg": 5.5},
                    }
                ],
            },
        )
        report = ValidationReport(
            results=[result],
            total_objects=1,
            passed=1,
            validation_level=2,
        )
        html_str = exporter.to_html(report)
        assert "dbo.orders" in html_str
        assert "MIN (src" in html_str or "1 → 1" in html_str
