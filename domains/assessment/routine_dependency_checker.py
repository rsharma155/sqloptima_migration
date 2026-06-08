"""
Module: routine_dependency_checker.py
Purpose: Enrich routine assessments with table/view dependencies and target readiness.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from application.go_engine_migration.target_table_preflight import _locate_target_table
from domains.assessment.assessment_engine import MigrationTier, RoutineAssessment
from domains.migration.target_schema_resolver import resolve_target_schema

DependencyStatus = str  # "on_target" | "included_in_job" | "missing" | "unchecked"


@dataclass(frozen=True)
class RoutineTableDependency:
    """A table or view referenced by a stored procedure or function."""

    source_schema: str
    object_name: str
    object_type: str
    target_schema: str
    target_object: str
    status: DependencyStatus

    @property
    def source_qualified(self) -> str:
        return f"{self.source_schema}.{self.object_name}"

    @property
    def target_qualified(self) -> str:
        return f"{self.target_schema}.{self.target_object}"


def _routine_key(schema: str, name: str) -> tuple[str, str]:
    return schema.lower(), name.lower()


def index_routine_table_dependencies(
    rows: list[dict[str, Any]],
) -> dict[tuple[str, str], list[tuple[str, str, str]]]:
    """Group dependency rows by (referencing_schema, referencing_object)."""
    grouped: dict[tuple[str, str], list[tuple[str, str, str]]] = {}
    seen: set[tuple[str, str, str, str]] = set()
    for row in rows:
        ref_schema = str(row.get("referencing_schema") or "").strip()
        ref_object = str(row.get("referencing_object") or "").strip()
        dep_schema = str(row.get("referenced_schema") or "").strip()
        dep_object = str(row.get("referenced_object") or "").strip()
        dep_type = str(row.get("referenced_type") or "USER_TABLE")
        if not ref_schema or not ref_object or not dep_schema or not dep_object:
            continue
        dedupe_key = (ref_schema.lower(), ref_object.lower(), dep_schema.lower(), dep_object.lower())
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        grouped.setdefault(_routine_key(ref_schema, ref_object), []).append(
            (dep_schema, dep_object, dep_type),
        )
    return grouped


async def _dependency_status(
    *,
    source_schema: str,
    object_name: str,
    migration_source_schema: str,
    target_schema: str,
    target_connector: Any | None,
    selected_tables: set[str] | None,
) -> DependencyStatus:
    if (
        selected_tables
        and source_schema.lower() == migration_source_schema.lower()
        and object_name.lower() in selected_tables
    ):
        return "included_in_job"

    if target_connector is None:
        return "unchecked"

    pg_object = object_name.lower()
    found_schema, _, _ = await _locate_target_table(
        target_connector,
        table_name=pg_object,
        target_schema=target_schema,
        source_schema=source_schema,
    )
    if found_schema:
        return "on_target"
    return "missing"


async def enrich_routine_assessments(
    assessments: list[RoutineAssessment],
    *,
    dependency_rows: list[dict[str, Any]],
    migration_source_schema: str,
    target_schema: str | None = None,
    target_connector: Any | None = None,
    selected_tables: list[str] | None = None,
) -> None:
    """Attach table dependencies and upgrade tier when prerequisites are missing."""
    grouped = index_routine_table_dependencies(dependency_rows)
    selected = {name.lower() for name in (selected_tables or [])}

    for assessment in assessments:
        key = _routine_key(assessment.schema_name, assessment.routine_name)
        deps_raw = grouped.get(key, [])
        if not deps_raw:
            continue

        table_dependencies: list[RoutineTableDependency] = []
        missing_on_target: list[str] = []

        for dep_schema, dep_object, dep_type in deps_raw:
            resolved_target_schema = resolve_target_schema(dep_schema, target_schema)
            status = await _dependency_status(
                source_schema=dep_schema,
                object_name=dep_object,
                migration_source_schema=migration_source_schema,
                target_schema=resolved_target_schema,
                target_connector=target_connector,
                selected_tables=selected,
            )
            dep = RoutineTableDependency(
                source_schema=dep_schema,
                object_name=dep_object,
                object_type=dep_type,
                target_schema=resolved_target_schema,
                target_object=dep_object.lower(),
                status=status,
            )
            table_dependencies.append(dep)
            if status == "missing":
                missing_on_target.append(dep.target_qualified)

        assessment.table_dependencies = [
            {
                "source_schema": d.source_schema,
                "object_name": d.object_name,
                "object_type": d.object_type,
                "target_schema": d.target_schema,
                "target_object": d.target_object,
                "status": d.status,
            }
            for d in table_dependencies
        ]
        assessment.missing_target_tables = missing_on_target

        if missing_on_target:
            names = ", ".join(sorted(missing_on_target))
            assessment.blockers.append(
                f"Missing required table(s)/view(s) on PostgreSQL target: {names} — "
                "migrate those objects first or include them in this job"
            )
            assessment.migration_tier = MigrationTier.BLOCKER
            assessment.prerequisites.append(
                "Migrate referenced tables/views to PostgreSQL before deploying routines"
            )
        elif any(d.status == "unchecked" for d in table_dependencies):
            unchecked = [
                d.source_qualified for d in table_dependencies if d.status == "unchecked"
            ]
            assessment.warnings.append(
                f"References {', '.join(sorted(unchecked))} — connect a target database "
                "during assessment to verify these exist on PostgreSQL"
            )
            if assessment.migration_tier == MigrationTier.SAFE:
                assessment.migration_tier = MigrationTier.WARNING
            assessment.prerequisites.append(
                "Verify referenced tables/views exist on the PostgreSQL target before migrating routines"
            )
        elif any(d.status == "included_in_job" for d in table_dependencies):
            included = [
                d.source_qualified
                for d in table_dependencies
                if d.status == "included_in_job"
            ]
            assessment.prerequisites.append(
                f"Will use tables from this job: {', '.join(sorted(included))}"
            )
