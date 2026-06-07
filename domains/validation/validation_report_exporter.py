"""
Module: domains/validation/validation_report_exporter.py
Purpose: Exports ValidationReport objects to JSON, CSV and HTML formats.
         No I/O beyond what callers provide — returns strings, not files.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import csv
import html
import io
import json
from datetime import UTC, datetime
from typing import Any

from domains.validation.validation_engine import (
    ValidationReport,
    ValidationResult,
    ValidationStatus,
)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class ValidationReportExporter:
    """Converts a :class:`ValidationReport` into portable export formats.

    All methods are *synchronous* — they operate on an already-computed
    :class:`ValidationReport` and do not perform any I/O.

    Example::

        exporter = ValidationReportExporter()
        json_str = exporter.to_json(report)
        html_str = exporter.to_html(report)
        csv_str  = exporter.to_csv(report)
    """

    # ------------------------------------------------------------------
    # JSON
    # ------------------------------------------------------------------

    def to_json(self, report: ValidationReport, indent: int = 2) -> str:
        """Serialise *report* as a JSON string."""
        return json.dumps(self._report_to_dict(report), indent=indent, default=str)

    # ------------------------------------------------------------------
    # CSV
    # ------------------------------------------------------------------

    def to_csv(self, report: ValidationReport) -> str:
        """Serialise all :class:`ValidationResult` rows as CSV.

        Each row represents one result entry.  Issues are flattened to a
        semicolon-separated string in a single ``issues`` column.
        """
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(
            [
                "validation_id",
                "object_name",
                "category",
                "status",
                "source_count",
                "target_count",
                "duration_ms",
                "issues",
            ]
        )
        for r in report.results:
            issues_text = "; ".join(i.message for i in r.issues)
            writer.writerow(
                [
                    str(r.validation_id),
                    r.object_name,
                    r.category.value if hasattr(r.category, "value") else r.category,
                    r.status.value if hasattr(r.status, "value") else r.status,
                    r.source_count,
                    r.target_count,
                    round(r.duration_ms, 3),
                    issues_text,
                ]
            )
        return buf.getvalue()

    # ------------------------------------------------------------------
    # HTML
    # ------------------------------------------------------------------

    def to_html(self, report: ValidationReport) -> str:
        """Serialise *report* as a self-contained HTML document."""
        generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

        rows_html = "\n".join(_result_row(r) for r in report.results)
        status_val = report.overall_status.value.upper()
        stat_total = f'<div class="stat-num">{report.total_objects}</div><div>Total</div>'
        stat_pass = (
            f'<div class="stat" style="background:#d5f5e3">'
            f'<div class="stat-num">{report.passed}</div><div>Passed</div></div>'
        )
        stat_fail = (
            f'<div class="stat" style="background:#fadbd8">'
            f'<div class="stat-num">{report.failed}</div><div>Failed</div></div>'
        )
        stat_warn = (
            f'<div class="stat" style="background:#fdebd0">'
            f'<div class="stat-num">{report.warnings}</div><div>Warnings</div></div>'
        )

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Migration Validation Report</title>
  <style>
    body{{font-family:Arial,sans-serif;margin:2rem;color:#333}}
    h1{{color:#2c3e50}}
    .badge{{display:inline-block;padding:.25rem .6rem;border-radius:.3rem;
            color:#fff;font-weight:bold;font-size:.85rem}}
    .PASSED{{background:#27ae60}} .FAILED{{background:#e74c3c}}
    .WARNING{{background:#e67e22}} .ERROR{{background:#8e44ad}}
    .SKIPPED{{background:#95a5a6}}
    table{{width:100%;border-collapse:collapse;margin-top:1rem}}
    th{{background:#2c3e50;color:#fff;padding:.5rem;text-align:left}}
    td{{padding:.4rem .5rem;border-bottom:1px solid #ddd;vertical-align:top}}
    tr:hover{{background:#f5f5f5}}
    .issues{{font-size:.8rem;color:#666}}
    .summary{{display:flex;gap:2rem;margin:1rem 0}}
    .stat{{text-align:center;padding:1rem;border-radius:.5rem;background:#ecf0f1}}
    .stat-num{{font-size:2rem;font-weight:bold}}
  </style>
</head>
<body>
  <h1>Migration Validation Report</h1>
  <p>Generated: {html.escape(generated_at)}</p>
  <p>Overall status: <span class="badge {status_val}">{status_val}</span></p>
  <div class="summary">
    <div class="stat">{stat_total}</div>
    {stat_pass}
    {stat_fail}
    {stat_warn}
  </div>
  <table>
    <thead>
      <tr>
        <th>Object</th><th>Category</th><th>Status</th>
        <th>Source Count</th><th>Target Count</th><th>Issues</th>
      </tr>
    </thead>
    <tbody>
{rows_html}
    </tbody>
  </table>
  <p style="color:#999;font-size:.8rem;margin-top:2rem">
    SQL Server → PostgreSQL Migration Platform
    &nbsp;|&nbsp; Copyright &copy; 2026 Ravi Sharma
  </p>
</body>
</html>"""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _report_to_dict(report: ValidationReport) -> dict[str, Any]:
        return {
            "report_id": str(report.report_id),
            "generated_at": datetime.now(UTC).isoformat(),
            "overall_status": (
                report.overall_status.value
                if hasattr(report.overall_status, "value")
                else report.overall_status
            ),
            "summary": {
                "total_objects": report.total_objects,
                "passed": report.passed,
                "failed": report.failed,
                "warnings": report.warnings,
                "duration_ms": report.duration_ms,
            },
            "results": [_result_to_dict(r) for r in report.results],
        }


# ---------------------------------------------------------------------------
# Module-level helpers (not exposed in __all__)
# ---------------------------------------------------------------------------


def _result_to_dict(r: ValidationResult) -> dict[str, Any]:
    return {
        "validation_id": str(r.validation_id),
        "object_name": r.object_name,
        "category": r.category.value if hasattr(r.category, "value") else r.category,
        "status": r.status.value if hasattr(r.status, "value") else r.status,
        "source_count": r.source_count,
        "target_count": r.target_count,
        "duration_ms": r.duration_ms,
        "issues": [
            {
                "category": (
                    i.category.value if hasattr(i.category, "value") else i.category
                ),
                "severity": i.severity,
                "message": i.message,
                "source_value": i.source_value,
                "target_value": i.target_value,
            }
            for i in r.issues
        ],
        "details": r.details,
    }


def _result_row(r: ValidationResult) -> str:
    status_str = r.status.value.upper() if hasattr(r.status, "value") else str(r.status).upper()
    category_str = r.category.value if hasattr(r.category, "value") else str(r.category)
    issues_text = "<br>".join(
        html.escape(i.message) for i in r.issues
    ) if r.issues else "—"
    src = html.escape(str(r.source_count)) if r.source_count is not None else "—"
    tgt = html.escape(str(r.target_count)) if r.target_count is not None else "—"
    return (
        f'      <tr>'
        f'<td>{html.escape(r.object_name)}</td>'
        f'<td>{html.escape(category_str)}</td>'
        f'<td><span class="badge {status_str}">{status_str}</span></td>'
        f'<td>{src}</td><td>{tgt}</td>'
        f'<td class="issues">{issues_text}</td>'
        f'</tr>'
    )


def _status_color(status: ValidationStatus) -> str:
    mapping = {
        ValidationStatus.PASSED: "#27ae60",
        ValidationStatus.FAILED: "#e74c3c",
        ValidationStatus.WARNING: "#e67e22",
        ValidationStatus.ERROR: "#8e44ad",
        ValidationStatus.SKIPPED: "#95a5a6",
    }
    return mapping.get(status, "#333")
