"""
Module: domains/chunking/datetime_chunk_planner.py
Purpose: Datetime-aware chunk planner that estimates rows per day and sets step
         size based on target chunk row count, avoiding huge/empty chunks from
         arbitrary fixed intervals.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from domains.chunking.chunk_planner import ChunkBoundary, ChunkPlan, ChunkStatus
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)

_DEFAULT_TARGET_CHUNK_SIZE = 10_000
_MIN_STEP_DAYS = 1
_MAX_STEP_DAYS = 365


@dataclass
class DatetimeChunkResult:
    chunks: list[ChunkPlan] = field(default_factory=list)
    step_days: int = 1
    rows_per_day_estimate: float = 0.0
    total_days: int = 0


class DatetimeChunkPlanner:
    """Plans chunks for tables with a datetime watermark column.

    Algorithm:
    1. Query MIN / MAX of the datetime column.
    2. Estimate rows per day = COUNT(*) / total_days (or fallback to 1).
    3. Compute step = target_chunk_rows / rows_per_day, clamped to [1, 365].
    4. Emit consecutive [start, end) half-open day-boundary chunks.
    """

    def __init__(self, connector: Any, target_chunk_size: int = _DEFAULT_TARGET_CHUNK_SIZE) -> None:
        self._connector = connector
        self._target_chunk_size = target_chunk_size

    async def plan(
        self,
        schema: str,
        table: str,
        datetime_col: str,
    ) -> DatetimeChunkResult:
        """Return a list of ChunkPlan objects covering the full datetime range."""
        min_dt, max_dt, total_rows = await self._query_bounds(schema, table, datetime_col)
        if min_dt is None or max_dt is None:
            logger.info("Datetime planner: table appears empty", table=table)
            return DatetimeChunkResult()

        total_days = max(1, (max_dt - min_dt).days)
        rows_per_day = total_rows / total_days if total_rows > 0 else 1.0
        step_days = max(_MIN_STEP_DAYS, min(_MAX_STEP_DAYS, int(self._target_chunk_size / rows_per_day)))

        chunks: list[ChunkPlan] = []
        cursor = min_dt.replace(tzinfo=None) if min_dt.tzinfo else min_dt
        end_dt = max_dt.replace(tzinfo=None) if max_dt.tzinfo else max_dt
        step = timedelta(days=step_days)

        while cursor <= end_dt:
            chunk_end = min(cursor + step - timedelta(seconds=1), end_dt)
            chunks.append(
                ChunkPlan(
                    chunk_id=uuid4(),
                    table_name=table,
                    schema_name=schema,
                    column_name=datetime_col,
                    boundary=ChunkBoundary(start=cursor, end=chunk_end),
                    status=ChunkStatus.PENDING,
                )
            )
            cursor += step

        logger.info(
            "Datetime chunk plan created",
            table=table,
            total_chunks=len(chunks),
            step_days=step_days,
            rows_per_day=round(rows_per_day, 1),
        )
        return DatetimeChunkResult(
            chunks=chunks,
            step_days=step_days,
            rows_per_day_estimate=rows_per_day,
            total_days=total_days,
        )

    async def _query_bounds(
        self, schema: str, table: str, col: str
    ) -> tuple[datetime | None, datetime | None, int]:
        rows = await self._connector.execute(
            f"SELECT MIN([{col}]) AS min_dt, MAX([{col}]) AS max_dt, COUNT(*) AS cnt "
            f"FROM [{schema}].[{table}]"
        )
        if not rows:
            return None, None, 0
        row = rows[0]
        min_dt = row.get("min_dt")
        max_dt = row.get("max_dt")
        cnt = int(row.get("cnt", 0))
        if isinstance(min_dt, str):
            min_dt = datetime.fromisoformat(min_dt)
        if isinstance(max_dt, str):
            max_dt = datetime.fromisoformat(max_dt)
        return min_dt, max_dt, cnt
