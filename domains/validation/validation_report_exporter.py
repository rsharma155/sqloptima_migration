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
import math
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from domains.validation.validation_engine import (
    ValidationCategory,
    ValidationReport,
    ValidationResult,
    ValidationStatus,
)

_LEVEL_LABELS = {
    1: "L1 — Row Count",
    2: "L2 — Aggregates (MIN/MAX/SUM/AVG)",
    3: "L3 — Chunk-boundary validation",
}


class ValidationReportExporter:
    """Converts a :class:`ValidationReport` into portable export formats."""

    def to_json(self, report: ValidationReport, indent: int = 2) -> str:
        return json.dumps(self._report_to_dict(report), indent=indent, default=str)

    def to_csv(self, report: ValidationReport) -> str:
        category = _dominant_category(report)
        if category == ValidationCategory.AGGREGATE:
            return _aggregate_csv(report)
        if category == ValidationCategory.CHUNK:
            return _chunk_csv(report)
        return _row_count_csv(report)

    def to_html(self, report: ValidationReport) -> str:
        generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        level = report.validation_level
        level_label = _LEVEL_LABELS.get(level or 0, "Migration validation")
        status_val = report.overall_status.value.upper()

        category = _dominant_category(report)
        if category == ValidationCategory.AGGREGATE:
            body_rows = _aggregate_html_rows(report.results)
            table_header = (
                "        <th>Table</th><th>Column</th><th>Status</th>"
                "<th>MIN (src → tgt)</th><th>MAX (src → tgt)</th>"
                "<th>SUM (src → tgt)</th><th>AVG (src → tgt)</th><th>Notes</th>"
            )
        elif category == ValidationCategory.CHUNK:
            body_rows = _chunk_html_rows(report.results)
            table_header = (
                "        <th>Chunk</th><th>Status</th>"
                "<th>Source rows</th><th>Target rows</th><th>Issues</th>"
            )
        else:
            body_rows = _row_count_html_rows(report.results)
            table_header = (
                "        <th>Table</th><th>Status</th>"
                "<th>Source count</th><th>Target count</th><th>Issues</th>"
            )

        stat_total = (
            f'<div class="stat-num">{report.total_objects}</div><div>Tables</div>'
        )
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
  <title>{html.escape(level_label)} Report</title>
  <style>
    body{{font-family:Arial,sans-serif;margin:2rem;color:#333}}
    h1{{color:#2c3e50}}
    .badge{{display:inline-block;padding:.25rem .6rem;border-radius:.3rem;
            color:#fff;font-weight:bold;font-size:.85rem}}
    .PASSED{{background:#27ae60}} .FAILED{{background:#e74c3c}}
    .WARNING{{background:#e67e22}} .ERROR{{background:#8e44ad}}
    .SKIPPED{{background:#95a5a6}}
    table{{width:100%;border-collapse:collapse;margin-top:1rem;font-size:.9rem}}
    th{{background:#2c3e50;color:#fff;padding:.5rem;text-align:left}}
    td{{padding:.4rem .5rem;border-bottom:1px solid #ddd;vertical-align:top}}
    tr:hover{{background:#f5f5f5}}
    .issues{{font-size:.8rem;color:#666}}
    .summary{{display:flex;gap:2rem;margin:1rem 0}}
    .stat{{text-align:center;padding:1rem;border-radius:.5rem;background:#ecf0f1}}
    .stat-num{{font-size:2rem;font-weight:bold}}
    .mono{{font-family:Consolas,monospace;font-size:.85rem}}
  </style>
</head>
<body>
  <h1>{html.escape(level_label)}</h1>
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
{table_header}
      </tr>
    </thead>
    <tbody>
{body_rows}
    </tbody>
  </table>
  <p style="color:#999;font-size:.8rem;margin-top:2rem">
    SQL Server → PostgreSQL Migration Platform
    &nbsp;|&nbsp; Copyright &copy; 2026 Ravi Sharma
  </p>
</body>
</html>"""

    @staticmethod
    def _report_to_dict(report: ValidationReport) -> dict[str, Any]:
        level = report.validation_level
        return {
            "report_id": str(report.report_id),
            "generated_at": datetime.now(UTC).isoformat(),
            "validation_level": level,
            "validation_level_label": _LEVEL_LABELS.get(level or 0, ""),
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
            "results": [result_to_dict(r) for r in report.results],
        }


def json_safe_value(value: Any) -> Any:
    """Recursively convert DB driver types (Decimal, datetime, …) for JSON columns."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        num = float(value)
        if math.isfinite(num) and num == int(num) and abs(num) < 1e15:
            return int(num)
        return num
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, dict):
        return {str(k): json_safe_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe_value(v) for v in value]
    return value


def result_to_dict(r: ValidationResult) -> dict[str, Any]:
    vid = r.validation_id
    return json_safe_value({
        "validation_id": str(vid) if vid is not None else None,
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
                "details": i.details,
            }
            for i in r.issues
        ],
        "details": r.details,
    })


def _dominant_category(report: ValidationReport) -> ValidationCategory:
    if report.validation_level == 2:
        return ValidationCategory.AGGREGATE
    if report.validation_level == 3:
        return ValidationCategory.CHUNK
    if report.results:
        return report.results[0].category
    return ValidationCategory.ROW_COUNT


def _status_badge(status: ValidationStatus | str) -> str:
    status_str = status.value.upper() if hasattr(status, "value") else str(status).upper()
    return f'<span class="badge {status_str}">{status_str}</span>'


def _fmt_pair(src: Any, tgt: Any) -> str:
    if src is None and tgt is None:
        return "—"
    return html.escape(f"{src} → {tgt}")


def _aggregate_html_rows(results: list[ValidationResult]) -> str:
    rows: list[str] = []
    for r in results:
        table_name = html.escape(r.object_name)
        column_results = r.details.get("column_results") or []
        if not column_results:
            issues = "<br>".join(html.escape(i.message) for i in r.issues) or "—"
            rows.append(
                f"      <tr><td>{table_name}</td><td colspan=\"7\">"
                f"{_status_badge(r.status)}</td></tr>"
            )
            continue
        for idx, col in enumerate(column_results):
            src = col.get("source") or {}
            tgt = col.get("target") or {}
            notes = col.get("reason") or "; ".join(col.get("mismatches") or [])
            if col.get("status") == "failed" and not notes:
                notes = "value mismatch"
            rows.append(
                "      <tr>"
                f"<td>{table_name if idx == 0 else ''}</td>"
                f"<td class=\"mono\">{html.escape(str(col.get('column', '')))}</td>"
                f"<td>{_status_badge(str(col.get('status', '')))}</td>"
                f"<td class=\"mono\">{_fmt_pair(src.get('min'), tgt.get('min'))}</td>"
                f"<td class=\"mono\">{_fmt_pair(src.get('max'), tgt.get('max'))}</td>"
                f"<td class=\"mono\">{_fmt_pair(src.get('sum'), tgt.get('sum'))}</td>"
                f"<td class=\"mono\">{_fmt_pair(src.get('avg'), tgt.get('avg'))}</td>"
                f"<td class=\"issues\">{html.escape(notes) if notes else '—'}</td>"
                "</tr>"
            )
    return "\n".join(rows)


def _chunk_html_rows(results: list[ValidationResult]) -> str:
    rows: list[str] = []
    for r in results:
        issues = "<br>".join(html.escape(i.message) for i in r.issues) or "—"
        rows.append(
            "      <tr>"
            f"<td class=\"mono\">{html.escape(r.object_name)}</td>"
            f"<td>{_status_badge(r.status)}</td>"
            f"<td>{html.escape(str(r.source_count if r.source_count is not None else '—'))}</td>"
            f"<td>{html.escape(str(r.target_count if r.target_count is not None else '—'))}</td>"
            f"<td class=\"issues\">{issues}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def _row_count_html_rows(results: list[ValidationResult]) -> str:
    rows: list[str] = []
    for r in results:
        issues = "<br>".join(html.escape(i.message) for i in r.issues) or "—"
        src = html.escape(str(r.source_count)) if r.source_count is not None else "—"
        tgt = html.escape(str(r.target_count)) if r.target_count is not None else "—"
        basis = r.details.get("source_count_basis")
        if basis:
            src += f" <span class=\"issues\">({html.escape(str(basis))})</span>"
        rows.append(
            "      <tr>"
            f"<td>{html.escape(r.object_name)}</td>"
            f"<td>{_status_badge(r.status)}</td>"
            f"<td>{src}</td><td>{tgt}</td>"
            f"<td class=\"issues\">{issues}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def _row_count_csv(report: ValidationReport) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow([
        "validation_id", "object_name", "category", "status",
        "source_count", "target_count", "duration_ms", "issues",
    ])
    for r in report.results:
        writer.writerow([
            str(r.validation_id),
            r.object_name,
            r.category.value,
            r.status.value,
            r.source_count,
            r.target_count,
            round(r.duration_ms, 3),
            "; ".join(i.message for i in r.issues),
        ])
    return buf.getvalue()


def _aggregate_csv(report: ValidationReport) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow([
        "table", "column", "status",
        "min_source", "min_target", "max_source", "max_target",
        "sum_source", "sum_target", "avg_source", "avg_target", "notes",
    ])
    for r in report.results:
        for col in r.details.get("column_results") or []:
            src = col.get("source") or {}
            tgt = col.get("target") or {}
            notes = col.get("reason") or "; ".join(col.get("mismatches") or [])
            writer.writerow([
                r.object_name,
                col.get("column", ""),
                col.get("status", ""),
                src.get("min"), tgt.get("min"),
                src.get("max"), tgt.get("max"),
                src.get("sum"), tgt.get("sum"),
                src.get("avg"), tgt.get("avg"),
                notes,
            ])
    return buf.getvalue()


def _chunk_csv(report: ValidationReport) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow([
        "chunk", "status", "source_count", "target_count", "pk_start", "pk_end", "issues",
    ])
    for r in report.results:
        writer.writerow([
            r.object_name,
            r.status.value,
            r.source_count,
            r.target_count,
            r.details.get("pk_start"),
            r.details.get("pk_end"),
            "; ".join(i.message for i in r.issues),
        ])
    return buf.getvalue()
