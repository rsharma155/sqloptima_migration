"""
Integration contract tests for Go engine dispatch (masking + transforms).

Live SQL Server / PostgreSQL tests require docker-compose sample-dbs profile and
INTEGRATION_GO_ENGINE=1; otherwise these tests verify dispatch payload shape only.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

from application.go_engine_migration.go_job_dispatch_builder import GoJobDispatchBuilder
from domains.migration.migration_engine import MigrationJob, MigrationStrategy, TableMigrationPlan


def test_masking_transforms_embedded_in_go_dispatch_payload():
    job = MigrationJob(
        source_connection_id=uuid4(),
        target_connection_id=uuid4(),
        tables=[
            TableMigrationPlan(
                table_name="Users",
                schema_name="dbo",
                target_schema="public",
                columns=["Id", "Email"],
                row_count_estimate=100,
                strategy=MigrationStrategy.CHUNKED,
                column_transforms={"Email": "mask_partial_email"},
                column_sensitivity={"Email": "pii"},
                column_types={"Email": "nvarchar"},
            )
        ],
    )
    cfg = GoJobDispatchBuilder().build(
        job,
        source_schema="dbo",
        target_schema="public",
        resolved_columns_by_table={"Users": ["Id", "Email"]},
    )
    table = cfg.tables[0]
    assert table.column_transforms.get("Email") == "mask_partial_email"
    assert table.column_sensitivity.get("Email") == "pii"
    assert table.column_types.get("Email") == "nvarchar"


@pytest.mark.integration
@pytest.mark.skipif(
    os.getenv("INTEGRATION_GO_ENGINE") != "1",
    reason="Set INTEGRATION_GO_ENGINE=1 with docker SQL Server + PostgreSQL to run live test",
)
def test_live_go_engine_env_documented():
    """Placeholder gate — run Go integration tests separately via go test -tags integration."""
    required = [
        "MIGRATION_SOURCE_HOST",
        "MIGRATION_TARGET_HOST",
    ]
    missing = [k for k in required if not os.getenv(k)]
    assert not missing, f"Missing env for live Go engine test: {missing}"
