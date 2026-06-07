"""Executive assessment report — ROI, risk score, timeline (§13.6).
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


# USD per core/year — conservative SQL Server Standard estimate (configurable).
_LICENSE_PER_CORE_YEAR = 3_717.0
_EFFORT_HOURS_PER_OBJECT = {
    "auto_convertible": 0.1,
    "partial": 2.0,
    "unsupported": 8.0,
    "risky": 4.0,
    "performance_risk": 3.0,
}


@dataclass
class ExecutiveAssessmentReport:
    project_name: str
    source_database: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    sql_server_cores: int = 4
    sql_server_edition: str = "Standard"
    total_objects: int = 0
    blocker_count: int = 0
    warning_count: int = 0
    auto_convertible_pct: float = 100.0
    estimated_person_days: float = 0.0
    estimated_license_savings_usd: float = 0.0
    migration_risk_score: int = 0  # 0 = low risk, 100 = high risk
    projected_timeline_weeks: int = 4
    executive_summary: str = ""
    phases: list[dict[str, Any]] = field(default_factory=list)


class ExecutiveReportBuilder:
    """Produce a business-facing summary from technical assessment metrics."""

    def build(
        self,
        *,
        project_name: str,
        source_database: str,
        total_objects: int,
        auto_convertible: int,
        partial: int,
        unsupported: int,
        risky: int,
        blocker_count: int = 0,
        warning_count: int = 0,
        sql_server_cores: int = 4,
        sql_server_edition: str = "Standard",
    ) -> ExecutiveAssessmentReport:
        auto_pct = round((auto_convertible / total_objects * 100) if total_objects else 100, 1)
        person_hours = (
            auto_convertible * _EFFORT_HOURS_PER_OBJECT["auto_convertible"]
            + partial * _EFFORT_HOURS_PER_OBJECT["partial"]
            + unsupported * _EFFORT_HOURS_PER_OBJECT["unsupported"]
            + risky * _EFFORT_HOURS_PER_OBJECT["risky"]
        )
        person_days = round(person_hours / 8, 1)
        license_savings = round(sql_server_cores * _LICENSE_PER_CORE_YEAR, 0)

        risk = min(100, int(
            unsupported * 8
            + partial * 3
            + risky * 5
            + blocker_count * 10
            + max(0, 100 - auto_pct)
        ))

        weeks = max(2, min(24, int(person_days / 5) + (1 if blocker_count else 0)))

        summary = (
            f"Retiring {source_database} on SQL Server {sql_server_edition} "
            f"({sql_server_cores} cores) could save ~${license_savings:,.0f}/year in licensing. "
            f"{auto_pct}% of {total_objects} objects auto-convert; "
            f"estimated {person_days} person-days over ~{weeks} weeks. "
            f"Migration risk score: {risk}/100."
        )

        phases = [
            {"phase": 1, "name": "Assess & Plan", "weeks": max(1, weeks // 4)},
            {"phase": 2, "name": "Migrate Waves", "weeks": max(2, weeks // 2)},
            {"phase": 3, "name": "Validate & Cutover", "weeks": max(1, weeks // 4)},
            {"phase": 4, "name": "Stabilize", "weeks": 2},
        ]

        return ExecutiveAssessmentReport(
            project_name=project_name,
            source_database=source_database,
            sql_server_cores=sql_server_cores,
            sql_server_edition=sql_server_edition,
            total_objects=total_objects,
            blocker_count=blocker_count,
            warning_count=warning_count,
            auto_convertible_pct=auto_pct,
            estimated_person_days=person_days,
            estimated_license_savings_usd=license_savings,
            migration_risk_score=risk,
            projected_timeline_weeks=weeks,
            executive_summary=summary,
            phases=phases,
        )

    def to_dict(self, report: ExecutiveAssessmentReport) -> dict[str, Any]:
        return {
            "project_name": report.project_name,
            "source_database": report.source_database,
            "created_at": report.created_at.isoformat(),
            "sql_server_cores": report.sql_server_cores,
            "sql_server_edition": report.sql_server_edition,
            "total_objects": report.total_objects,
            "blocker_count": report.blocker_count,
            "warning_count": report.warning_count,
            "auto_convertible_pct": report.auto_convertible_pct,
            "estimated_person_days": report.estimated_person_days,
            "estimated_license_savings_usd": report.estimated_license_savings_usd,
            "migration_risk_score": report.migration_risk_score,
            "projected_timeline_weeks": report.projected_timeline_weeks,
            "executive_summary": report.executive_summary,
            "phases": report.phases,
        }
