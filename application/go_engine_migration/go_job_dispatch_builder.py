"""
Module: go_job_dispatch_builder.py
Purpose: Build GoJobDispatchConfig from an in-memory MigrationJob.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from domains.migration.go_engine.go_connection_dispatch_ref import GoConnectionDispatchRef
from domains.migration.go_engine.go_executor_kind import GoExecutorKind
from domains.migration.go_engine.go_job_dispatch_config import GoJobDispatchConfig
from domains.migration.go_engine.go_table_dispatch_payload import GoTableDispatchPayload
from domains.migration.migration_engine import MigrationJob, MigrationStrategy
from domains.migration.source_throttle import SourceThrottleConfig


def _skip_data_load_for_table(
    job: MigrationJob,
    table_name: str,
) -> bool:
    from application.go_engine_migration.target_table_preflight import TargetTablePolicy

    policies = getattr(job, "target_table_policies", None) or {}
    return policies.get(table_name) == TargetTablePolicy.USE_EXISTING.value


class GoJobDispatchBuilder:
    """Maps domain MigrationJob + resolved columns into a Go dispatch contract."""

    def build(
        self,
        job: MigrationJob,
        *,
        source_schema: str,
        target_schema: str,
        resolved_columns_by_table: dict[str, list[str]],
        snapshot_ref: str | None = None,
        idempotent: bool = False,
        conflict_columns: list[str] | None = None,
        use_nolock: bool = False,
        source_throttle: SourceThrottleConfig | None = None,
    ) -> GoJobDispatchConfig:
        tables: list[GoTableDispatchPayload] = []
        for plan in job.tables:
            columns = resolved_columns_by_table.get(plan.table_name)
            if not columns:
                raise ValueError(f"Missing resolved columns for table {plan.table_name}")
            strategy = (
                plan.strategy.value
                if isinstance(plan.strategy, MigrationStrategy)
                else str(plan.strategy)
            )
            tables.append(
                GoTableDispatchPayload(
                    table_name=plan.table_name,
                    source_schema=plan.schema_name or source_schema,
                    target_schema=plan.target_schema or target_schema,
                    columns=columns,
                    chunk_size=plan.chunk_size,
                    parallel_workers=plan.parallel_workers,
                    strategy=strategy,
                    column_transforms=dict(plan.column_transforms or {}),
                    column_sensitivity=dict(plan.column_sensitivity or {}),
                    column_types=dict(plan.column_types or {}),
                    column_extract_casts=dict(plan.column_extract_casts or {}),
                    order_column=plan.order_column,
                    where_clause=plan.where_clause,
                    source_maxdop=plan.source_maxdop,
                    skip_data_load=_skip_data_load_for_table(job, plan.table_name),
                    row_count_estimate=int(plan.row_count_estimate or 0),
                    table_size_mb=float(getattr(plan, "table_size_mb", 0.0) or 0.0),
                    chunk_delay_sec=float(getattr(plan, "chunk_delay_sec", 0.0) or 0.0),
                )
            )

        throttle = source_throttle or getattr(job, "source_throttle", None) or SourceThrottleConfig()
        config = GoJobDispatchConfig(
            job_id=job.job_id,
            executor=GoExecutorKind.GO,
            source=GoConnectionDispatchRef(job.source_connection_id, source_schema),
            target=GoConnectionDispatchRef(job.target_connection_id, target_schema),
            tables=tuple(tables),
            snapshot_ref=snapshot_ref,
            idempotent=idempotent,
            conflict_columns=tuple(conflict_columns or ()),
            use_nolock=use_nolock,
            source_throttle=throttle,
        )
        config.validate()
        return config
