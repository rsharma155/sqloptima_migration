"""
Module: target_table_preflight.py
Purpose: Inspect PostgreSQL target tables before migration and detect paused jobs
         that can be resumed instead of starting a duplicate run.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID

from application.go_engine_migration.target_table_provisioner import (
    get_target_table_row_count,
    target_table_exists,
)
from application.migration_service import _derive_job_status, list_jobs, refresh_all_jobs_from_metadata
from domains.migration.migration_engine import MigrationStatus
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)


class TargetTablePolicy(StrEnum):
    """How to handle an existing target table before data load."""

    USE_EXISTING = "use_existing"
    DROP_EMPTY_RECREATE = "drop_empty_recreate"
    TRUNCATE_RELOAD = "truncate_reload"


class TargetTablePreflightError(ValueError):
    """Raised when migration cannot proceed without an explicit table policy."""


def _suggest_policy(exists: bool, row_count: int) -> TargetTablePolicy | None:
    if not exists:
        return None
    if row_count == 0:
        return TargetTablePolicy.DROP_EMPTY_RECREATE
    # Default to skip reload when data is already present — user opts into truncate explicitly.
    return TargetTablePolicy.USE_EXISTING


def _alternate_schemas(target_schema: str, source_schema: str) -> list[str]:
    """Schemas to search when a table is missing from the resolved target schema."""
    seen = {target_schema.lower()}
    alternates: list[str] = []
    for candidate in ("public", source_schema):
        key = candidate.lower()
        if key not in seen:
            alternates.append(candidate)
            seen.add(key)
    return alternates


async def _locate_target_table(
    target_connector: Any,
    *,
    table_name: str,
    target_schema: str,
    source_schema: str,
) -> tuple[str | None, int, bool]:
    """Return (schema_found, row_count, schema_mismatch)."""
    if await target_table_exists(target_connector, target_schema, table_name):
        row_count = await get_target_table_row_count(
            target_connector, target_schema, table_name,
        )
        return target_schema, row_count, False

    for alt_schema in _alternate_schemas(target_schema, source_schema):
        if await target_table_exists(target_connector, alt_schema, table_name):
            row_count = await get_target_table_row_count(
                target_connector, alt_schema, table_name,
            )
            return alt_schema, row_count, True

    return None, 0, False


async def inspect_target_tables(
    target_connector: Any,
    *,
    target_schema: str,
    table_names: list[str],
    source_schema: str = "dbo",
) -> list[dict[str, Any]]:
    """Return per-table existence and row counts on the PostgreSQL target."""
    results: list[dict[str, Any]] = []
    for table_name in table_names:
        found_schema, row_count, schema_mismatch = await _locate_target_table(
            target_connector,
            table_name=table_name,
            target_schema=target_schema,
            source_schema=source_schema,
        )
        exists = found_schema is not None
        suggested = _suggest_policy(exists, row_count)
        requires_action = exists
        message = "Table does not exist — will be created before migration."
        found_in_schema: str | None = None

        if exists and schema_mismatch and found_schema:
            found_in_schema = found_schema
            requires_action = True
            message = (
                f"Table exists in schema {found_schema!r} but migration targets "
                f"{target_schema!r}. Update the target schema to {found_schema!r} "
                f"or move the table before migrating."
            )
        elif exists and row_count == 0:
            message = "Table exists but is empty — it can be dropped and recreated."
        elif exists and row_count > 0:
            message = (
                f"Table exists with {row_count:,} row(s) — skip data load if already migrated, "
                "truncate and reload for a full refresh, or resume a paused migration."
            )

        results.append({
            "table_name": table_name,
            "exists": exists,
            "row_count": row_count,
            "requires_action": requires_action,
            "suggested_policy": suggested.value if suggested else None,
            "found_in_schema": found_in_schema,
            "schema_mismatch": schema_mismatch,
            "message": message,
        })
    return results


async def find_paused_migration_jobs(
    source_connection_id: UUID | str,
    target_connection_id: UUID | str,
    *,
    table_names: list[str],
    target_schema: str,
) -> list[dict[str, Any]]:
    """Find paused jobs on the same route that overlap selected tables."""
    await refresh_all_jobs_from_metadata()
    src_id = str(source_connection_id)
    tgt_id = str(target_connection_id)
    selected = {t.lower() for t in table_names}
    matches: list[dict[str, Any]] = []

    for job_id, job in list_jobs():
        if str(job.source_connection_id) != src_id:
            continue
        if str(job.target_connection_id) != tgt_id:
            continue
        if _derive_job_status(job) != MigrationStatus.PAUSED:
            continue

        overlapping: list[dict[str, Any]] = []
        for plan in job.tables:
            if (plan.target_schema or "public") != target_schema:
                continue
            if plan.table_name.lower() not in selected:
                continue
            overlapping.append({
                "table_name": plan.table_name,
                "status": plan.status,
                "rows_migrated": plan.rows_migrated or 0,
                "row_count_estimate": plan.row_count_estimate or 0,
            })

        if not overlapping:
            continue

        matches.append({
            "job_id": str(job_id),
            "status": MigrationStatus.PAUSED.value,
            "overlapping_tables": overlapping,
            "rows_migrated": sum(t["rows_migrated"] for t in overlapping),
            "message": (
                "Paused migration can resume from the last checkpoint without "
                "re-loading completed chunks."
            ),
        })

    return matches


def validate_table_policies(
    preflight_tables: list[dict[str, Any]],
    table_policies: dict[str, str] | None,
) -> None:
    """Ensure every existing target table has an explicit policy before dispatch."""
    if not table_policies:
        table_policies = {}

    missing: list[str] = []
    for entry in preflight_tables:
        if entry.get("schema_mismatch"):
            raise TargetTablePreflightError(entry.get("message") or "Target schema mismatch")
        if not entry.get("requires_action"):
            continue
        name = entry["table_name"]
        policy = table_policies.get(name)
        if not policy:
            missing.append(name)
            continue
        if policy not in {p.value for p in TargetTablePolicy}:
            raise TargetTablePreflightError(
                f"Unknown policy {policy!r} for table {name}"
            )
        row_count = int(entry.get("row_count") or 0)
        if policy == TargetTablePolicy.DROP_EMPTY_RECREATE.value and row_count > 0:
            raise TargetTablePreflightError(
                f"Table {name} has {row_count:,} row(s) — use truncate_reload or resume "
                "a paused job instead of drop_empty_recreate."
            )

    if missing:
        raise TargetTablePreflightError(
            "Target table conflict — choose a policy for: "
            + ", ".join(missing)
        )

