"""Unit tests for pre-migration readiness validation."""

from __future__ import annotations

import pytest

from application.migration_readiness_service import (
    MigrationReadinessError,
    assert_routines_ready_for_migration,
    assert_tables_ready_for_migration,
    selected_routine_blockers,
    selected_table_blockers,
)
from domains.assessment.assessment_engine import (
    DatabaseAssessment,
    MigrationTier,
    RoutineAssessment,
    TableAssessment,
)


def _table(name: str, tier: MigrationTier, blockers: list[str] | None = None) -> TableAssessment:
    return TableAssessment(
        table_name=name,
        schema_name="dbo",
        migration_tier=tier,
        blockers=blockers or [],
    )


def test_selected_table_blockers_returns_blocker_tables():
    assessment = DatabaseAssessment(
        database_name="AppDb",
        tables=[
            _table("Customers", MigrationTier.SAFE),
            _table("Geo", MigrationTier.BLOCKER, ["geometry column requires PostGIS"]),
        ],
    )
    blocked = selected_table_blockers(assessment, ["Customers", "Geo"])
    assert len(blocked) == 1
    assert blocked[0][0] == "Geo"
    assert "PostGIS" in blocked[0][1][0]


def test_assert_tables_ready_allows_with_type_overrides():
    ta = TableAssessment(
        table_name="dt_MiscTypes",
        schema_name="dbo",
        migration_tier=MigrationTier.BLOCKER,
        blocker_types=["col_sql_variant"],
        unsupported_type_columns=[
            {"column_name": "col_sql_variant", "source_type": "sql_variant"},
        ],
        blockers=[
            "Column 'col_sql_variant' uses unsupported type 'sql_variant' — choose a PostgreSQL target type"
        ],
    )
    assessment = DatabaseAssessment(database_name="AppDb", tables=[ta])
    assert_tables_ready_for_migration(
        assessment,
        ["dt_MiscTypes"],
        column_type_overrides={"dt_MiscTypes.col_sql_variant": "sql_variant_text"},
    )


def test_assert_tables_ready_raises_for_blockers():
    assessment = DatabaseAssessment(
        database_name="AppDb",
        tables=[_table("Bad", MigrationTier.BLOCKER, ["unsupported hierarchyid"])],
    )
    with pytest.raises(MigrationReadinessError, match="BLOCKER"):
        assert_tables_ready_for_migration(assessment, ["Bad"])


def test_assert_tables_ready_allows_safe_tables():
    assessment = DatabaseAssessment(
        database_name="AppDb",
        tables=[_table("Customers", MigrationTier.SAFE)],
    )
    assert_tables_ready_for_migration(assessment, ["Customers"])


def _routine(name: str, tier: MigrationTier, blockers: list[str] | None = None) -> RoutineAssessment:
    return RoutineAssessment(
        routine_name=name,
        schema_name="dbo",
        object_type="procedure",
        migration_tier=tier,
        blockers=blockers or [],
    )


def test_selected_routine_blockers_returns_blocker_routines():
    assessment = DatabaseAssessment(
        database_name="AppDb",
        routines=[
            _routine("usp_ok", MigrationTier.SAFE),
            _routine(
                "uspGetBillOfMaterials",
                MigrationTier.BLOCKER,
                ["Missing required table(s)/view(s) on PostgreSQL target: Production.billofmaterials"],
            ),
        ],
    )
    blocked = selected_routine_blockers(assessment, ["uspGetBillOfMaterials"], [])
    assert len(blocked) == 1
    assert blocked[0][0] == "procedure uspGetBillOfMaterials"
    assert "Production.billofmaterials" in blocked[0][1][0]


def test_assert_routines_ready_raises_for_missing_dependencies():
    assessment = DatabaseAssessment(
        database_name="AppDb",
        routines=[
            _routine(
                "uspGetEmployeeManagers",
                MigrationTier.BLOCKER,
                ["Missing required table(s)/view(s) on PostgreSQL target: HumanResources.employee"],
            ),
        ],
    )
    with pytest.raises(MigrationReadinessError, match="routine"):
        assert_routines_ready_for_migration(assessment, ["uspGetEmployeeManagers"], [])
