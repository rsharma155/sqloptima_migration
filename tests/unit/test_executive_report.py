"""Tests for executive assessment report (§13.6)."""
from domains.reporting.executive_report import ExecutiveReportBuilder


def test_executive_report_includes_roi_and_risk():
    builder = ExecutiveReportBuilder()
    report = builder.build(
        project_name="Acme Exit",
        source_database="OrdersDB",
        total_objects=100,
        auto_convertible=80,
        partial=15,
        unsupported=3,
        risky=2,
        blocker_count=1,
        sql_server_cores=8,
    )
    assert report.estimated_license_savings_usd > 0
    assert 0 <= report.migration_risk_score <= 100
    assert report.estimated_person_days > 0
    assert report.executive_summary
    data = builder.to_dict(report)
    assert data["project_name"] == "Acme Exit"
    assert len(data["phases"]) >= 3
