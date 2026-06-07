"""
Module: tests/unit/test_assessment_engine.py
Purpose: Unit tests for the AssessmentEngine domain — verifies tier assignment,
         complexity scoring, LOB detection, CI collation detection, and
         migration time estimates.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import pytest

from domains.assessment.assessment_engine import (
    AssessmentEngine,
    MigrationTier,
)
from shared.kernel.database_object import Column, DataType, Table


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_table(
    name: str = "orders",
    schema: str = "dbo",
    columns: list[Column] | None = None,
    row_count: int = 0,
    is_temporal: bool = False,
    is_memory_optimized: bool = False,
) -> Table:
    return Table(
        database_name="AdventureWorks",
        schema_name=schema,
        object_name=name,
        row_count_estimate=row_count,
        is_temporal=is_temporal,
        is_memory_optimized=is_memory_optimized,
        columns=columns or [],
    )


def _make_col(
    name: str,
    type_name: str,
    max_length: int = 100,
    collation: str | None = None,
    is_identity: bool = False,
    is_computed: bool = False,
    is_nullable: bool = True,
) -> Column:
    from uuid import UUID
    return Column(
        table_id=UUID(int=0),
        column_name=name,
        ordinal_position=1,
        data_type=DataType(
            type_name=type_name,
            max_length=max_length,
            is_nullable=is_nullable,
        ),
        is_identity=is_identity,
        is_computed=is_computed,
        is_nullable=is_nullable,
        collation_name=collation,
    )


# ---------------------------------------------------------------------------
# Tier: SAFE tables
# ---------------------------------------------------------------------------


class TestSafeTables:
    def test_simple_int_table_is_safe(self):
        engine = AssessmentEngine()
        table = _make_table(columns=[
            _make_col("id", "int", is_identity=True),
            _make_col("name", "varchar", max_length=100),
        ], row_count=1000)
        result = engine.assess_table(table)
        assert result.migration_tier == MigrationTier.SAFE
        assert result.complexity_score < 30
        assert result.lob_columns == []
        assert result.blockers == []

    def test_small_table_has_short_estimate(self):
        engine = AssessmentEngine()
        table = _make_table(
            columns=[_make_col("id", "int", is_identity=True)],
            row_count=6_000,
        )
        result = engine.assess_table(table)
        # 6000 rows / 60000 rows-per-minute = 0.1 min
        assert result.estimated_minutes == pytest.approx(0.1, abs=0.05)


# ---------------------------------------------------------------------------
# LOB detection
# ---------------------------------------------------------------------------


class TestLobDetection:
    @pytest.mark.parametrize("type_name,max_len", [
        ("varchar", -1),
        ("nvarchar", -1),
        ("varbinary", -1),
        ("text", 100),
        ("ntext", 100),
        ("image", 100),
        ("xml", 100),
    ])
    def test_lob_column_detected(self, type_name: str, max_len: int):
        engine = AssessmentEngine()
        table = _make_table(columns=[
            _make_col("id", "int", is_identity=True),
            _make_col("payload", type_name, max_length=max_len),
        ])
        result = engine.assess_table(table)
        assert "payload" in result.lob_columns

    def test_lob_column_increases_score(self):
        engine = AssessmentEngine()
        table_no_lob = _make_table(columns=[_make_col("id", "int", is_identity=True)])
        table_with_lob = _make_table(columns=[
            _make_col("id", "int", is_identity=True),
            _make_col("body", "nvarchar", max_length=-1),
        ])
        score_base = engine.assess_table(table_no_lob).complexity_score
        score_lob = engine.assess_table(table_with_lob).complexity_score
        assert score_lob > score_base

    def test_lob_tier_is_at_least_warning(self):
        engine = AssessmentEngine()
        table = _make_table(columns=[
            _make_col("id", "int", is_identity=True),
            _make_col("body", "text"),
        ])
        result = engine.assess_table(table)
        assert result.migration_tier in (MigrationTier.WARNING, MigrationTier.BLOCKER)

    def test_lob_throughput_estimate_lower_than_normal(self):
        engine = AssessmentEngine()
        cols_normal = [_make_col("id", "int", is_identity=True)]
        cols_lob = [
            _make_col("id", "int", is_identity=True),
            _make_col("doc", "text"),
        ]
        est_normal = engine.assess_table(_make_table(columns=cols_normal, row_count=100_000)).estimated_minutes
        est_lob = engine.assess_table(_make_table(columns=cols_lob, row_count=100_000)).estimated_minutes
        assert est_lob > est_normal


# ---------------------------------------------------------------------------
# Collation detection
# ---------------------------------------------------------------------------


class TestCollationDetection:
    def test_ci_collation_detected(self):
        engine = AssessmentEngine()
        table = _make_table(columns=[
            _make_col("id", "int", is_identity=True),
            _make_col("name", "varchar", collation="SQL_Latin1_General_CP1_CI_AS"),
        ])
        result = engine.assess_table(table)
        assert "name" in result.ci_collation_columns

    def test_cs_collation_not_flagged(self):
        engine = AssessmentEngine()
        table = _make_table(columns=[
            _make_col("id", "int", is_identity=True),
            _make_col("name", "varchar", collation="SQL_Latin1_General_CP1_CS_AS"),
        ])
        result = engine.assess_table(table)
        assert result.ci_collation_columns == []

    def test_ci_collation_prereq_included(self):
        engine = AssessmentEngine()
        table = _make_table(columns=[
            _make_col("name", "varchar", collation="Latin1_General_CI_AI"),
        ])
        result = engine.assess_table(table)
        assert any("citext" in p.lower() for p in result.prerequisites)


# ---------------------------------------------------------------------------
# Blocker types
# ---------------------------------------------------------------------------


class TestBlockerTypes:
    @pytest.mark.parametrize("type_name", ["hierarchyid", "geography", "geometry", "sql_variant"])
    def test_blocker_type_produces_blocker_tier(self, type_name: str):
        engine = AssessmentEngine()
        table = _make_table(columns=[
            _make_col("id", "int", is_identity=True),
            _make_col("location", type_name),
        ])
        result = engine.assess_table(table)
        assert result.migration_tier == MigrationTier.BLOCKER
        assert result.blockers  # non-empty

    def test_blocker_type_listed_in_blocker_types(self):
        engine = AssessmentEngine()
        table = _make_table(columns=[_make_col("path", "hierarchyid")])
        result = engine.assess_table(table)
        assert "path" in result.blocker_types


# ---------------------------------------------------------------------------
# Special table flags
# ---------------------------------------------------------------------------


class TestSpecialFlags:
    def test_temporal_table_is_warning(self):
        engine = AssessmentEngine()
        table = _make_table(is_temporal=True, columns=[_make_col("id", "int", is_identity=True)])
        result = engine.assess_table(table)
        assert result.migration_tier in (MigrationTier.WARNING, MigrationTier.BLOCKER)
        assert any("temporal" in w.lower() for w in result.warnings)

    def test_memory_optimized_table_warns(self):
        engine = AssessmentEngine()
        table = _make_table(is_memory_optimized=True, columns=[_make_col("id", "int", is_identity=True)])
        result = engine.assess_table(table)
        assert result.migration_tier in (MigrationTier.WARNING, MigrationTier.BLOCKER)

    def test_no_identity_column_warns(self):
        engine = AssessmentEngine()
        table = _make_table(columns=[_make_col("id", "int", is_identity=False)])
        result = engine.assess_table(table)
        assert any("IDENTITY" in w or "identity" in w.lower() for w in result.warnings)

    def test_large_table_adds_prerequisite(self):
        engine = AssessmentEngine()
        table = _make_table(
            row_count=2_000_000,
            columns=[_make_col("id", "int", is_identity=True)],
        )
        result = engine.assess_table(table)
        assert result.prerequisites  # non-empty


# ---------------------------------------------------------------------------
# Database-level assessment
# ---------------------------------------------------------------------------


class TestDatabaseAssessment:
    def test_all_safe_tables_yields_safe_db(self):
        engine = AssessmentEngine()
        tables = [
            _make_table("t1", columns=[_make_col("id", "int", is_identity=True)]),
            _make_table("t2", columns=[_make_col("id", "int", is_identity=True)]),
        ]
        result = engine.assess_database("TestDB", tables)
        assert result.overall_tier == MigrationTier.SAFE
        assert result.safe_count == 2
        assert result.warning_count == 0
        assert result.blocker_count == 0

    def test_one_blocker_makes_db_blocker(self):
        engine = AssessmentEngine()
        tables = [
            _make_table("safe", columns=[_make_col("id", "int", is_identity=True)]),
            _make_table("bad", columns=[_make_col("loc", "geography")]),
        ]
        result = engine.assess_database("TestDB", tables)
        assert result.overall_tier == MigrationTier.BLOCKER
        assert result.blocker_count == 1

    def test_cdc_disabled_adds_global_prereq(self):
        engine = AssessmentEngine()
        result = engine.assess_database("DB", [], cdc_enabled_db=False)
        assert any("cdc" in p.lower() for p in result.global_prerequisites)

    def test_cdc_enabled_no_cdc_prereq(self):
        engine = AssessmentEngine()
        result = engine.assess_database("DB", [], cdc_enabled_db=True)
        assert not any("cdc" in p.lower() for p in result.global_prerequisites)

    def test_linked_server_adds_global_prereq(self):
        engine = AssessmentEngine()
        linked = [{"referenced_server": "REMOTE_SRV", "referencing_object": "usp_fetch"}]
        result = engine.assess_database("DB", [], cdc_enabled_db=True, linked_server_refs=linked)
        assert any("linked server" in p.lower() for p in result.global_prerequisites)

    def test_total_estimate_is_sum_of_tables(self):
        engine = AssessmentEngine()
        tables = [
            _make_table("a", row_count=60_000, columns=[_make_col("id", "int", is_identity=True)]),
            _make_table("b", row_count=60_000, columns=[_make_col("id", "int", is_identity=True)]),
        ]
        result = engine.assess_database("DB", tables)
        # Each table: 60k / 60k rows-per-min = 1 min  →  total ≈ 2 min
        assert result.estimated_total_minutes == pytest.approx(2.0, abs=0.2)


# ---------------------------------------------------------------------------
# Global temp table refs (Phase 4)
# ---------------------------------------------------------------------------


class TestGlobalTempTableRefs:
    def test_global_temp_refs_add_prereq(self):
        engine = AssessmentEngine()
        refs = [
            {"object_name": "usp_load_staging", "schema_name": "dbo", "object_type": "SQL_STORED_PROCEDURE"},
            {"object_name": "usp_transform",    "schema_name": "dbo", "object_type": "SQL_STORED_PROCEDURE"},
        ]
        result = engine.assess_database("DB", [], cdc_enabled_db=True, global_temp_table_refs=refs)
        assert any("##" in p or "global temp" in p.lower() for p in result.global_prerequisites)

    def test_global_temp_refs_names_mentioned_in_prereq(self):
        engine = AssessmentEngine()
        refs = [{"object_name": "usp_etl", "schema_name": "dbo", "object_type": "PROCEDURE"}]
        result = engine.assess_database("DB", [], cdc_enabled_db=True, global_temp_table_refs=refs)
        prereq_text = " ".join(result.global_prerequisites)
        assert "usp_etl" in prereq_text

    def test_no_global_temp_refs_no_extra_prereq(self):
        engine = AssessmentEngine()
        result = engine.assess_database("DB", [], cdc_enabled_db=True, global_temp_table_refs=[])
        assert not any("##" in p for p in result.global_prerequisites)

    def test_global_temp_refs_stored_on_assessment(self):
        engine = AssessmentEngine()
        refs = [{"object_name": "usp_x", "schema_name": "dbo", "object_type": "PROCEDURE"}]
        result = engine.assess_database("DB", [], cdc_enabled_db=True, global_temp_table_refs=refs)
        assert result.global_temp_table_refs == refs


# ---------------------------------------------------------------------------
# Agent jobs (Phase 4)
# ---------------------------------------------------------------------------


class TestAgentJobs:
    def test_agent_jobs_add_prereq(self):
        engine = AssessmentEngine()
        jobs = [{"job_name": "NightlyLoad", "is_enabled": True, "step_name": "ExtractStep", "step_command": "..."}]
        result = engine.assess_database("DB", [], cdc_enabled_db=True, agent_jobs=jobs)
        assert any("agent job" in p.lower() or "pg_cron" in p.lower() for p in result.global_prerequisites)

    def test_agent_job_name_mentioned_in_prereq(self):
        engine = AssessmentEngine()
        jobs = [{"job_name": "WeeklyArchive", "is_enabled": True, "step_name": "s1", "step_command": "..."}]
        result = engine.assess_database("DB", [], cdc_enabled_db=True, agent_jobs=jobs)
        prereq_text = " ".join(result.global_prerequisites)
        assert "WeeklyArchive" in prereq_text

    def test_no_agent_jobs_no_agent_prereq(self):
        engine = AssessmentEngine()
        result = engine.assess_database("DB", [], cdc_enabled_db=True, agent_jobs=[])
        assert not any("agent job" in p.lower() for p in result.global_prerequisites)

    def test_agent_jobs_stored_on_assessment(self):
        engine = AssessmentEngine()
        jobs = [{"job_name": "J1", "is_enabled": False, "step_name": "s1", "step_command": "..."}]
        result = engine.assess_database("DB", [], cdc_enabled_db=True, agent_jobs=jobs)
        assert result.agent_jobs == jobs


# ---------------------------------------------------------------------------
# SqlServerMetadataDiscovery — Agent Jobs query exists (unit smoke test)
# ---------------------------------------------------------------------------


class TestAgentJobsDiscoveryMethod:
    def test_discover_agent_jobs_graceful_on_failure(self):
        """discover_agent_jobs swallows connector errors and returns []."""
        from unittest.mock import AsyncMock
        from infrastructure.sqlserver.sqlserver_discovery import SqlServerMetadataDiscovery

        mock_connector = AsyncMock()
        mock_connector.execute = AsyncMock(side_effect=Exception("msdb unavailable"))
        discovery = SqlServerMetadataDiscovery(mock_connector)
        import asyncio
        result = asyncio.run(discovery.discover_agent_jobs("MyDB"))
        assert result == []
