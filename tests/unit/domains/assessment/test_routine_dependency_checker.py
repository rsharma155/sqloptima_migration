"""Unit tests for routine table dependency enrichment during assessment."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from domains.assessment.assessment_engine import MigrationTier, RoutineAssessment
from domains.assessment.routine_dependency_checker import (
    enrich_routine_assessments,
    index_routine_table_dependencies,
)


def _routine(name: str = "usp_example") -> RoutineAssessment:
    return RoutineAssessment(
        routine_name=name,
        schema_name="dbo",
        object_type="procedure",
        migration_tier=MigrationTier.SAFE,
    )


def test_index_routine_table_dependencies_dedupes_rows():
    rows = [
        {
            "referencing_schema": "dbo",
            "referencing_object": "uspGetBillOfMaterials",
            "referenced_schema": "Production",
            "referenced_object": "BillOfMaterials",
            "referenced_type": "USER_TABLE",
        },
        {
            "referencing_schema": "dbo",
            "referencing_object": "uspGetBillOfMaterials",
            "referenced_schema": "Production",
            "referenced_object": "BillOfMaterials",
            "referenced_type": "USER_TABLE",
        },
    ]
    grouped = index_routine_table_dependencies(rows)
    assert grouped[("dbo", "uspgetbillofmaterials")] == [
        ("Production", "BillOfMaterials", "USER_TABLE"),
    ]


@pytest.mark.asyncio
async def test_enrich_marks_missing_target_tables_as_blocker():
    assessment = _routine("uspGetBillOfMaterials")
    target = AsyncMock()
    target.execute = AsyncMock(return_value=[{"exists": False}])

    await enrich_routine_assessments(
        [assessment],
        dependency_rows=[
            {
                "referencing_schema": "dbo",
                "referencing_object": "uspGetBillOfMaterials",
                "referenced_schema": "Production",
                "referenced_object": "BillOfMaterials",
                "referenced_type": "USER_TABLE",
            }
        ],
        migration_source_schema="dbo",
        target_schema="public",
        target_connector=target,
        selected_tables=[],
    )

    assert assessment.migration_tier == MigrationTier.BLOCKER
    assert "Production.billofmaterials" in assessment.missing_target_tables
    assert any("Missing required table" in msg for msg in assessment.blockers)


@pytest.mark.asyncio
async def test_enrich_allows_tables_included_in_same_job():
    assessment = _routine("uspCustomers")
    target = AsyncMock()
    target.execute = AsyncMock(return_value=[{"exists": False}])

    await enrich_routine_assessments(
        [assessment],
        dependency_rows=[
            {
                "referencing_schema": "dbo",
                "referencing_object": "uspCustomers",
                "referenced_schema": "dbo",
                "referenced_object": "Customers",
                "referenced_type": "USER_TABLE",
            }
        ],
        migration_source_schema="dbo",
        target_schema="public",
        target_connector=target,
        selected_tables=["Customers"],
    )

    assert assessment.migration_tier == MigrationTier.SAFE
    assert assessment.missing_target_tables == []
    assert assessment.table_dependencies[0]["status"] == "included_in_job"


@pytest.mark.asyncio
async def test_enrich_without_target_connection_warns():
    assessment = _routine("uspGetEmployeeManagers")

    await enrich_routine_assessments(
        [assessment],
        dependency_rows=[
            {
                "referencing_schema": "dbo",
                "referencing_object": "uspGetEmployeeManagers",
                "referenced_schema": "HumanResources",
                "referenced_object": "Employee",
                "referenced_type": "USER_TABLE",
            }
        ],
        migration_source_schema="dbo",
        target_schema=None,
        target_connector=None,
        selected_tables=[],
    )

    assert assessment.migration_tier == MigrationTier.WARNING
    assert assessment.table_dependencies[0]["status"] == "unchecked"
    assert any("connect a target database" in w.lower() for w in assessment.warnings)
