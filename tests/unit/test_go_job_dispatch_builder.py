"""
Module: test_go_job_dispatch_builder.py
Purpose: Unit tests for GoJobDispatchBuilder.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from uuid import uuid4

from application.go_engine_migration.go_job_dispatch_builder import GoJobDispatchBuilder
from domains.migration.migration_engine import MigrationJob, MigrationStrategy, TableMigrationPlan


def test_build_dispatch_config_from_job():
    job = MigrationJob(
        source_connection_id=uuid4(),
        target_connection_id=uuid4(),
        tables=[
            TableMigrationPlan(
                table_name="Customers",
                schema_name="dbo",
                target_schema="public",
                columns=["Id"],
                row_count_estimate=100,
                strategy=MigrationStrategy.CHUNKED,
                order_column="CreatedAt",
                where_clause="IsActive = 1",
                source_maxdop=4,
            )
        ],
    )
    cfg = GoJobDispatchBuilder().build(
        job,
        source_schema="dbo",
        target_schema="public",
        resolved_columns_by_table={"Customers": ["Id", "Name"]},
        conflict_columns=["Id"],
        use_nolock=True,
    )
    assert cfg.tables[0].columns == ["Id", "Name"]
    assert cfg.target.schema == "public"
    assert cfg.tables[0].order_column == "CreatedAt"
    assert cfg.tables[0].where_clause == "IsActive = 1"
    assert cfg.tables[0].source_maxdop == 4
    assert cfg.conflict_columns == ("Id",)
    assert cfg.use_nolock is True
