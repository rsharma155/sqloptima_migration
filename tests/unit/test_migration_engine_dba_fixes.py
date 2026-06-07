"""
Module: tests/unit/test_migration_engine_dba_fixes.py
Purpose: TDD tests for DBA feedback fix 1.2 — target schema hardcoded to "public".
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import pytest

from domains.migration.migration_engine import TableMigrationPlan, MigrationStrategy


class TestTargetSchemaPlan:
    """
    Issue 1.2: target_schema must be a first-class field on TableMigrationPlan.
    The engine must use plan.target_schema when calling load_chunk, never a
    hardcoded "public".
    """

    def test_target_schema_defaults_to_public(self):
        plan = TableMigrationPlan(
            table_name="orders",
            schema_name="dbo",
            columns=["id", "name"],
            row_count_estimate=1000,
            strategy=MigrationStrategy.CHUNKED,
        )
        assert plan.target_schema == "public", (
            "target_schema must default to 'public' for backward compatibility"
        )

    def test_target_schema_can_be_set(self):
        plan = TableMigrationPlan(
            table_name="orders",
            schema_name="dbo",
            columns=["id", "name"],
            row_count_estimate=1000,
            strategy=MigrationStrategy.CHUNKED,
            target_schema="finance",
        )
        assert plan.target_schema == "finance"

    def test_source_maxdop_defaults_to_one(self):
        """Issue 9.1: source_maxdop must be configurable (default 1 = safe)."""
        plan = TableMigrationPlan(
            table_name="orders",
            schema_name="dbo",
            columns=["id"],
            row_count_estimate=1000,
            strategy=MigrationStrategy.CHUNKED,
        )
        assert plan.source_maxdop == 1

    def test_source_maxdop_can_be_raised(self):
        plan = TableMigrationPlan(
            table_name="orders",
            schema_name="dbo",
            columns=["id"],
            row_count_estimate=1000,
            strategy=MigrationStrategy.CHUNKED,
            source_maxdop=4,
        )
        assert plan.source_maxdop == 4
