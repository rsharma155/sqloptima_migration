"""
Module: reporting_engine.py
Purpose: Migration assessment report generation
Author: Migration Platform Team
Created: 2026-05-22
Domain: Reporting
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


class ReportFormat(StrEnum):
    JSON = "json"
    MARKDOWN = "markdown"
    HTML = "html"


@dataclass
class ObjectSummary:
    """Summary of a single database object in the report."""

    name: str = ""
    object_type: str = ""
    schema_name: str = ""
    status: str = "auto_convertible"
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    complexity: str = "simple"
    estimated_effort_minutes: int = 0


@dataclass
class AssessmentSection:
    """A section in the assessment report."""

    title: str = ""
    content: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    objects: list[ObjectSummary] = field(default_factory=list)


@dataclass
class MigrationReport:
    """Complete migration assessment report."""

    report_id: UUID = field(default_factory=uuid4)
    project_name: str = ""
    source_database: str = ""
    target_database: str = "PostgreSQL"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    sections: list[AssessmentSection] = field(default_factory=list)

    total_objects: int = 0
    auto_convertible: int = 0
    partial: int = 0
    unsupported: int = 0
    risky: int = 0
    estimated_downtime_minutes: int = 0
    estimated_effort_hours: float = 0.0
    auto_convertible_percentage: float = 100.0


class ReportingEngine:
    """Generates migration assessment reports from analysis results."""

    def generate_report(
        self,
        project_name: str,
        source_database: str,
        compatibility_results: list[Any],
        object_details: list[dict] | None = None,
    ) -> MigrationReport:
        """Generate a comprehensive migration assessment report."""
        report = MigrationReport(
            project_name=project_name,
            source_database=source_database,
        )

        # Summary section
        total = len(compatibility_results)
        auto = sum(1 for r in compatibility_results if r.status.value == "auto_convertible")
        partial = sum(1 for r in compatibility_results if r.status.value == "partial")
        unsupported = sum(1 for r in compatibility_results if r.status.value == "unsupported")
        risky = sum(1 for r in compatibility_results if r.status.value in ("risky", "performance_risk"))

        report.total_objects = total
        report.auto_convertible = auto
        report.partial = partial
        report.unsupported = unsupported
        report.risky = risky
        report.auto_convertible_percentage = round((auto / total * 100) if total else 100, 1)

        # Build sections
        summary = self._build_summary_section(report, compatibility_results)
        report.sections.append(summary)

        if object_details:
            details = self._build_objects_section(object_details)
            report.sections.append(details)

        issues = self._build_issues_section(compatibility_results)
        report.sections.append(issues)

        recommendations = self._build_recommendations_section(report)
        report.sections.append(recommendations)

        # Estimate
        report.estimated_effort_hours = self._estimate_effort(report)
        report.estimated_downtime_minutes = self._estimate_downtime(report)

        return report

    def _build_summary_section(
        self,
        report: MigrationReport,
        results: list[Any],
    ) -> AssessmentSection:
        objects = []
        for r in results:
            obj = r.object if hasattr(r, "object") else None
            objects.append(ObjectSummary(
                name=obj.object_name if obj else "",
                object_type=obj.object_type.value if obj else "",
                schema_name=obj.schema_name if obj else "",
                status=r.status.value if hasattr(r, "status") else "unknown",
                issues=[i.message for i in (r.issues or [])[:3]],
                complexity=r.object.compatibility_status.value if hasattr(r, "object") else "",
            ))

        return AssessmentSection(
            title="Migration Summary",
            content=self._generate_summary_text(report),
            metrics={
                "total_objects": report.total_objects,
                "auto_convertible": report.auto_convertible,
                "partial": report.partial,
                "unsupported": report.unsupported,
                "risky": report.risky,
                "auto_convertible_pct": report.auto_convertible_percentage,
                "estimated_effort_hours": report.estimated_effort_hours,
                "estimated_downtime_minutes": report.estimated_downtime_minutes,
            },
            objects=objects,
        )

    def _build_objects_section(self, object_details: list[dict]) -> AssessmentSection:
        objects = []
        for detail in object_details:
            objects.append(ObjectSummary(
                name=detail.get("name", ""),
                object_type=detail.get("type", ""),
                schema_name=detail.get("schema", ""),
                status=detail.get("status", "auto_convertible"),
                issues=detail.get("issues", []),
                warnings=detail.get("warnings", []),
            ))
        return AssessmentSection(
            title="Object Details",
            content=f"Detailed breakdown of {len(objects)} database objects.",
            objects=objects,
        )

    def _build_issues_section(self, results: list[Any]) -> AssessmentSection:
        all_issues: list[str] = []
        for r in results:
            for issue in getattr(r, "issues", []):
                obj_name = getattr(r, "object", None)
                prefix = obj_name.fully_qualified_name if obj_name else ""
                all_issues.append(f"[{prefix}] {issue.message}")

        return AssessmentSection(
            title="Issues & Warnings",
            content=f"Found {len(all_issues)} issues requiring attention.",
            objects=[],
            metrics={"total_issues": len(all_issues)},
        )

    def _build_recommendations_section(self, report: MigrationReport) -> AssessmentSection:
        recommendations = []
        if report.partial > 0:
            recommendations.append(
                f"Review {report.partial} partially convertible objects manually"
            )
        if report.unsupported > 0:
            recommendations.append(
                f"Plan alternatives for {report.unsupported} unsupported features"
            )
        if report.risky > 0:
            recommendations.append(
                f"Perform behavior validation for {report.risky} risky objects"
            )
        recommendations.append(
            "Run validation suite after migration to ensure data integrity"
        )
        recommendations.append(
            "Test application queries against migrated database before cutover"
        )

        return AssessmentSection(
            title="Recommendations",
            content="\n".join(f"- {r}" for r in recommendations),
            metrics={"recommendation_count": len(recommendations)},
        )

    def format_report(self, report: MigrationReport, fmt: ReportFormat = ReportFormat.MARKDOWN) -> str:
        """Format the report in the specified format."""
        if fmt == ReportFormat.MARKDOWN:
            return self._format_markdown(report)
        elif fmt == ReportFormat.JSON:
            import json
            return json.dumps(report.__dict__, default=str, indent=2)
        return str(report)

    @staticmethod
    def _generate_summary_text(report: MigrationReport) -> str:
        return (
            f"Migration assessment for {report.source_database} → {report.target_database}. "
            f"Total objects: {report.total_objects}. "
            f"Auto-convertible: {report.auto_convertible_percentage}%. "
            f"Estimated effort: {report.estimated_effort_hours:.1f} hours."
        )

    @staticmethod
    def _estimate_effort(report: MigrationReport) -> float:
        effort = 0.0
        effort += report.auto_convertible * 0.1
        effort += report.partial * 2.0
        effort += report.unsupported * 4.0
        effort += report.risky * 1.0
        return effort

    @staticmethod
    def _estimate_downtime(report: MigrationReport) -> int:
        base = report.total_objects * 2
        return min(base, 480)

    @staticmethod
    def _format_markdown(report: MigrationReport) -> str:
        lines = [
            "# Migration Assessment Report",
            "",
            f"**Project:** {report.project_name}",
            f"**Source:** {report.source_database}",
            f"**Target:** {report.target_database}",
            f"**Date:** {report.created_at.isoformat()}",
            "",
            "## Summary",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Total Objects | {report.total_objects} |",
            f"| Auto-Convertible | {report.auto_convertible} ({report.auto_convertible_percentage}%) |",
            f"| Partial | {report.partial} |",
            f"| Unsupported | {report.unsupported} |",
            f"| Risky | {report.risky} |",
            f"| Estimated Effort | {report.estimated_effort_hours:.1f} hours |",
            f"| Estimated Downtime | {report.estimated_downtime_minutes} min |",
            "",
            "## Sections",
            "",
        ]
        for section in report.sections:
            lines.append(f"### {section.title}")
            lines.append("")
            lines.append(section.content)
            lines.append("")

        return "\n".join(lines)
