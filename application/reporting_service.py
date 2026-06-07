"""
Module: application/reporting_service.py
Purpose: Generates human-readable migration reports by aggregating data from
         the metadata repository.  Produces Discovery, Assessment, Migration
         Progress, and Validation Summary reports in JSON, HTML, and CSV.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.metadata_db.repositories.job_repository import JobRepository
from infrastructure.metadata_db.repositories.validation_repository import (
    ValidationRepository,
)
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)


class ReportingServiceError(Exception):
    pass


class ReportingService:
    """Assembles and exports migration reports from persisted metadata.

    All report data is read from the metadata repository — no live DB
    connections to source or target are required at report time.

    Report types:
    * ``migration_summary`` — job status, rows migrated, timing
    * ``validation_summary`` — aggregated L1-L4 results and mismatch counts
    * ``quarantine_summary`` — rows that failed type conversion (future)
    """

    def __init__(self, session: AsyncSession) -> None:
        self._job_repo = JobRepository(session)
        self._val_repo = ValidationRepository(session)

    # ------------------------------------------------------------------
    # Migration summary report
    # ------------------------------------------------------------------

    async def migration_summary(self, job_id: str) -> dict[str, Any]:
        """Return a structured migration summary for *job_id*."""
        job = await self._job_repo.get_by_id(job_id)
        if job is None:
            raise ReportingServiceError(f"Migration job {job_id!r} not found")

        plans = []
        for plan in getattr(job, "table_plans", []):
            plans.append({
                "table": f"{plan.schema_name}.{plan.table_name}",
                "status": plan.status,
                "rows_migrated": plan.rows_migrated,
                "row_count_estimate": plan.row_count_estimate,
                "pct_complete": (
                    round(plan.rows_migrated / plan.row_count_estimate * 100, 1)
                    if plan.row_count_estimate
                    else 0.0
                ),
            })

        duration_s: float | None = None
        if job.started_at and job.completed_at:
            duration_s = (job.completed_at - job.started_at).total_seconds()

        return {
            "report_type": "migration_summary",
            "generated_at": datetime.now(UTC).isoformat(),
            "job_id": job_id,
            "status": job.status,
            "tables_total": job.tables_total,
            "tables_done": job.tables_done,
            "rows_total": job.rows_total,
            "rows_migrated": job.rows_migrated,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "duration_seconds": duration_s,
            "error": job.error,
            "table_plans": plans,
        }

    # ------------------------------------------------------------------
    # Validation summary report
    # ------------------------------------------------------------------

    async def validation_summary(self, job_id: str) -> dict[str, Any]:
        """Return aggregated validation results for all runs under *job_id*."""
        runs = await self._val_repo.get_runs_for_job(job_id)
        if not runs:
            raise ReportingServiceError(
                f"No validation runs found for job {job_id!r}"
            )

        levels_summary: list[dict[str, Any]] = []
        overall_passed = True

        for run in runs:
            mismatches = await self._val_repo.get_mismatches_for_run(run.validation_run_id)
            level_summary: dict[str, Any] = {
                "run_id": run.validation_run_id,
                "level": run.level,
                "status": run.status,
                "pass_count": run.pass_count,
                "fail_count": run.fail_count,
                "mismatch_count": len(mismatches),
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "completed_at": (
                    run.completed_at.isoformat() if run.completed_at else None
                ),
            }
            if run.fail_count and run.fail_count > 0:
                overall_passed = False
            levels_summary.append(level_summary)

        return {
            "report_type": "validation_summary",
            "generated_at": datetime.now(UTC).isoformat(),
            "job_id": job_id,
            "overall_passed": overall_passed,
            "total_runs": len(runs),
            "levels": levels_summary,
        }

    # ------------------------------------------------------------------
    # HTML rendering helpers
    # ------------------------------------------------------------------

    @staticmethod
    def migration_summary_html(summary: dict[str, Any]) -> str:
        """Convert a migration summary dict to a minimal HTML page."""
        status = summary.get("status", "unknown").upper()
        color = "#27ae60" if status == "COMPLETED" else "#e74c3c"
        rows = "\n".join(
            f"<tr><td>{p['table']}</td><td>{p['status']}</td>"
            f"<td>{p['rows_migrated']:,}</td>"
            f"<td>{p.get('pct_complete', 0):.1f}%</td></tr>"
            for p in summary.get("table_plans", [])
        )
        return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Migration Report</title>
<style>
body{{font-family:Arial,sans-serif;margin:2rem}}
table{{border-collapse:collapse;width:100%}}
th{{background:#2c3e50;color:#fff;padding:.4rem}}
td{{border-bottom:1px solid #ddd;padding:.4rem}}
.badge{{display:inline-block;padding:.2rem .5rem;border-radius:.3rem;color:#fff}}
</style></head>
<body>
<h1>Migration Report — Job {summary.get("job_id", "")}</h1>
<p>Status: <span class="badge" style="background:{color}">{status}</span></p>
<p>Generated: {summary.get("generated_at", "")}</p>
<p>Rows migrated: {summary.get("rows_migrated", 0):,} /
   {summary.get("rows_total", 0):,}</p>
<table>
<thead><tr><th>Table</th><th>Status</th><th>Rows</th><th>%</th></tr></thead>
<tbody>{rows}</tbody>
</table>
<p style="color:#999;font-size:.8rem">
SQL Server → PostgreSQL Migration Platform &nbsp;|&nbsp;
Copyright &copy; 2026 Ravi Sharma
</p>
</body></html>"""
