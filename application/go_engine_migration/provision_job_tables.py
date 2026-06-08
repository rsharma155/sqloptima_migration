"""
Module: provision_job_tables.py
Purpose: One-off target table provisioning for an existing migration job.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from uuid import UUID

from collections import defaultdict

from application.go_engine_migration.durable_migration_job_log_writer import (
    DurableMigrationJobLogWriter,
)
from application.go_engine_migration.target_table_provisioner import provision_target_tables
from application.migration_service import make_connector
from apps.api.connection_store import get_entry
from domains.migration.migration_engine import MigrationJob
from domains.migration.target_schema_resolver import resolve_target_schema
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)


async def provision_tables_for_job(job: MigrationJob) -> list[str]:
    """Create missing PostgreSQL tables for *job* without restarting the migration flow."""
    if not job.tables:
        raise ValueError("Job has no table plans")

    src_entry = get_entry(str(job.source_connection_id))
    tgt_entry = get_entry(str(job.target_connection_id))
    if not src_entry:
        raise ValueError("Source connection not found")
    if not tgt_entry:
        raise ValueError("Target connection not found")

    provision_groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for plan in job.tables:
        src = plan.schema_name or "dbo"
        tgt = resolve_target_schema(src, plan.target_schema)
        provision_groups[(src, tgt)].append(plan.table_name)

    src_connector, _ = await make_connector(src_entry)
    tgt_connector, _ = await make_connector(tgt_entry)
    await src_connector.connect()
    await tgt_connector.connect()
    try:
        created: list[str] = []
        for (source_schema, target_schema), table_names in provision_groups.items():
            batch = await provision_target_tables(
                src_connector,
                tgt_connector,
                database=src_entry.get("database", ""),
                source_schema=source_schema,
                target_schema=target_schema,
                table_names=table_names,
            )
            created.extend(batch)
    finally:
        await src_connector.disconnect()
        await tgt_connector.disconnect()

    if created:
        schemas_used = sorted({tgt for _, tgt in provision_groups})
        msg = (
            f"Provisioned {len(created)} target table(s) in {', '.join(schemas_used)}: "
            f"{', '.join(created)}"
        )
        writer = DurableMigrationJobLogWriter()
        await writer.append(str(job.job_id), msg, level="info")
        logger.info("provision_job_tables", job_id=str(job.job_id), tables=created)
    else:
        logger.info(
            "provision_job_tables_skipped",
            job_id=str(job.job_id),
            message="all target tables already exist",
        )

    return created


async def provision_tables_for_job_id(job_id: UUID) -> list[str]:
    """Load job from registry and provision its target tables."""
    from application import migration_service as svc

    job = svc.get_job(job_id)
    if job is None:
        job = await svc.refresh_job_from_metadata(job_id)
    if job is None:
        raise KeyError(f"Migration job not found: {job_id}")
    return await provision_tables_for_job(job)
