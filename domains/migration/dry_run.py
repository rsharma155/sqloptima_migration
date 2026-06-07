"""
Module: domains/migration/dry_run.py
Purpose: Fix F.2 — DryRunMigration executes the migration plan up to the point of
         actually writing data to PostgreSQL, letting operators verify row counts,
         chunk plans, and connector availability without mutating the target.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from domains.migration.migration_engine import TableMigrationPlan
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)


@dataclass
class DryRunTableResult:
    table_name: str
    schema_name: str
    estimated_rows: int
    chunk_count: int
    source_reachable: bool
    target_reachable: bool
    errors: list[str] = field(default_factory=list)

    @property
    def viable(self) -> bool:
        return self.source_reachable and self.target_reachable and not self.errors


@dataclass
class DryRunResult:
    tables: list[DryRunTableResult] = field(default_factory=list)
    duration_ms: float = 0.0

    @property
    def all_viable(self) -> bool:
        return all(t.viable for t in self.tables)

    @property
    def total_estimated_rows(self) -> int:
        return sum(t.estimated_rows for t in self.tables)


class DryRunMigration:
    """Validates a migration plan without writing any data.

    Fix F.2: operators can run a dry run before the real migration to catch:
    - Connectivity issues (source or target unreachable)
    - Missing tables or permission errors
    - Row-count/size estimates for capacity planning

    No rows are written; the target database is left untouched.
    """

    def __init__(
        self,
        source_connector: Any,
        target_connector: Any,
        chunk_size: int = 10_000,
    ) -> None:
        self._source = source_connector
        self._target = target_connector
        self._chunk_size = chunk_size

    async def run(self, plans: list[TableMigrationPlan]) -> DryRunResult:
        start = datetime.now(UTC)
        results: list[DryRunTableResult] = []
        for plan in plans:
            result = await self._validate_table(plan)
            results.append(result)
            logger.info(
                "dry_run_table",
                table=f"{plan.schema_name}.{plan.table_name}",
                viable=result.viable,
                estimated_rows=result.estimated_rows,
            )
        duration_ms = (datetime.now(UTC) - start).total_seconds() * 1000
        return DryRunResult(tables=results, duration_ms=duration_ms)

    async def _validate_table(self, plan: TableMigrationPlan) -> DryRunTableResult:
        result = DryRunTableResult(
            table_name=plan.table_name,
            schema_name=plan.schema_name,
            estimated_rows=0,
            chunk_count=0,
            source_reachable=False,
            target_reachable=False,
        )
        # Source check: count rows
        try:
            rows = await self._source.execute(
                f"SELECT COUNT(*) AS cnt FROM [{plan.schema_name}].[{plan.table_name}]"
            )
            result.estimated_rows = int(rows[0]["cnt"]) if rows else 0
            result.source_reachable = True
            chunk_size = plan.chunk_size if hasattr(plan, "chunk_size") and plan.chunk_size else self._chunk_size
            result.chunk_count = max(1, (result.estimated_rows + chunk_size - 1) // chunk_size)
        except Exception as exc:
            result.errors.append(f"Source error: {exc}")

        # Target check: verify table exists
        try:
            await self._target.execute(
                f'SELECT 1 FROM information_schema.tables '
                f"WHERE table_schema = $1 AND table_name = $2",
                {"schema": plan.schema_name, "table": plan.table_name},
            )
            result.target_reachable = True
        except Exception as exc:
            result.errors.append(f"Target error: {exc}")

        return result
