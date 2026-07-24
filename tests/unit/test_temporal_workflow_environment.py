# Author: Ravi Sharma
# Copyright (c) 2026 Ravi Sharma
# SPDX-License-Identifier: MIT

"""
Module: tests/unit/test_temporal_workflow_environment.py
Purpose: L-17 — Temporal WorkflowEnvironment integration tests (in-process worker)
Domain: Orchestration
Author: Ravi Sharma

These tests drive FullMigrationWorkflow against Temporal's in-memory test
server with stub activities. No external Temporal cluster is required.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

pytest.importorskip("temporalio")

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from domains.orchestration.workflows import FullMigrationWorkflow, MigrationWorkflowInput


@activity.defn(name="discover_objects")
async def stub_discover_objects(connection_id: str, schema: str) -> list[dict]:
    assert connection_id
    assert schema == "dbo"
    return [
        {
            "object_id": "1",
            "object_type": "TABLE",
            "name": "users",
            "schema": "dbo",
            "source_definition": "CREATE TABLE users (id INT)",
        }
    ]


@activity.defn(name="analyze_compatibility")
async def stub_analyze_compatibility(objects: list[dict]) -> list[dict]:
    return [{"name": o["name"], "compatible": True} for o in objects]


@activity.defn(name="convert_schema")
async def stub_convert_schema(object_id: str, sql: str) -> dict:
    return {"object_id": object_id, "success": True, "converted_sql": sql}


@activity.defn(name="migrate_table")
async def stub_migrate_table(
    schema: str,
    table: str,
    columns: list[str],
    chunk_size: int,
    parallel_workers: int,
) -> dict:
    return {"status": "completed", "rows_migrated": 10, "table": f"{schema}.{table}"}


@activity.defn(name="validate_table")
async def stub_validate_table(
    source_conn: str,
    target_conn: str,
    schema: str,
    table: str,
) -> dict:
    return {"status": "passed", "table": f"{schema}.{table}"}


@activity.defn(name="send_notification")
async def stub_send_notification(channel: str, message: str) -> None:
    assert channel
    assert message


@pytest.mark.asyncio
async def test_full_migration_workflow_with_temporal_environment() -> None:
    """L-17: run FullMigrationWorkflow on Temporal's in-process test server."""
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="migration-test",
            workflows=[FullMigrationWorkflow],
            activities=[
                stub_discover_objects,
                stub_analyze_compatibility,
                stub_convert_schema,
                stub_migrate_table,
                stub_validate_table,
                stub_send_notification,
            ],
        ):
            job_id = uuid4()
            result = await env.client.execute_workflow(
                FullMigrationWorkflow.run,
                MigrationWorkflowInput(
                    job_id=job_id,
                    source_connection_id="src-1",
                    target_connection_id="tgt-1",
                    schemas=["dbo"],
                    tables=["users"],
                    validate_after_migration=True,
                    notify_on_completion=True,
                ),
                id=f"full-migration-{job_id}",
                task_queue="migration-test",
                execution_timeout=timedelta(minutes=2),
            )

    assert result.success is True
    assert result.objects_discovered == 1
    assert result.tables_migrated == 1
    assert result.tables_validated == 1
    assert result.errors == []
