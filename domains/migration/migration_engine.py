"""
Module: migration_engine.py
Purpose: Chunked data migration engine
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

# SQL Server identifier whitelist: letters, digits, underscores, spaces, hyphens.
# Deliberately tight — rejects brackets, semicolons, quotes, and other injection chars.
_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_ \-]{0,127}$")


def _validate_identifier(value: str, label: str) -> None:
    """Raise ValueError if value is not a safe SQL Server identifier."""
    if not _IDENTIFIER_RE.match(value):
        raise ValueError(
            f"Invalid SQL identifier for {label!r}: {value!r}. "
            "Must start with a letter or underscore and contain only "
            "alphanumeric characters, underscores, spaces, or hyphens."
        )

from domains.chunking.chunk_planner import ChunkPlan, ChunkPlanner, ChunkStatus
from domains.chunking.chunk_store import ChunkStore
from domains.observability.metrics import (
    LatencyTracker,
    record_chunk_duration,
    record_failure,
    record_rows_migrated,
    set_active_workers,
)
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)

CHUNK_SIZE_MIN = 1000
CHUNK_SIZE_MAX = 100000
CHUNK_SIZE_DEFAULT = 10000
FETCH_TIME_FAST_SEC = 2.0
FETCH_TIME_SLOW_SEC = 10.0

RETRY_DELAYS_SEC = [0, 30, 120]


class MigrationStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    STOPPED = "stopped"
    PAUSED = "paused"
    RESUMED = "resumed"


class MigrationStrategy(StrEnum):
    FULL_LOAD = "full_load"
    CHUNKED = "chunked"
    PARALLEL_CHUNKED = "parallel_chunked"
    STREAMING = "streaming"


@dataclass
class ChunkResult:
    chunk_id: int
    rows_migrated: int
    start_time: datetime
    end_time: datetime
    success: bool
    error: str | None = None
    bytes_transferred: int = 0


@dataclass
class MigrationCheckpoint:
    table_name: str
    last_chunk_id: int
    last_offset: int
    total_rows_migrated: int
    status: MigrationStatus
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    checkpoint_id: UUID = field(default_factory=uuid4)
    # 1.7: persist adapted chunk size so restarts resume at the tuned value
    adapted_chunk_size: int = CHUNK_SIZE_DEFAULT


@dataclass
class MigrationProgress:
    table_name: str
    schema_name: str
    total_rows_estimate: int
    rows_migrated: int
    percentage: float
    current_chunk: int
    total_chunks: int
    status: MigrationStatus
    throughput_rows_per_sec: float
    elapsed_seconds: float
    estimated_remaining_seconds: float
    error: str | None = None


@dataclass
class TableMigrationPlan:
    table_name: str
    schema_name: str
    columns: list[str]
    row_count_estimate: int
    strategy: MigrationStrategy
    chunk_size: int = CHUNK_SIZE_DEFAULT
    parallel_workers: int = 4
    order_column: str | None = None
    where_clause: str | None = None
    status: str = "pending"
    rows_migrated: int = 0
    # Fix 1.2: target schema must not be hardcoded to "public"
    target_schema: str = "public"
    # Fix 9.1: MAXDOP is now configurable (default 1 = safe, raise for maintenance windows)
    source_maxdop: int = 1
    # §12.2 / F.4: per-column transforms (type coercion + PII masking)
    column_transforms: dict[str, str] | None = None
    column_sensitivity: dict[str, str] | None = None
    column_types: dict[str, str] | None = None
    column_extract_casts: dict[str, str] | None = None
    table_size_mb: float = 0.0
    chunk_delay_sec: float = 0.0


@dataclass
class TableMigrationResult:
    table_name: str
    schema_name: str
    rows_migrated: int
    chunks: list[ChunkResult]
    status: MigrationStatus
    start_time: datetime
    end_time: datetime | None = None
    error: str | None = None
    total_duration_seconds: float = 0.0
    throughput_rows_per_sec: float = 0.0


@dataclass
class MigrationJob:
    job_id: UUID = field(default_factory=uuid4)
    source_connection_id: UUID = field(default_factory=uuid4)
    target_connection_id: UUID = field(default_factory=uuid4)
    tables: list[TableMigrationPlan] = field(default_factory=list)
    status: MigrationStatus = MigrationStatus.PENDING
    results: list[TableMigrationResult] = field(default_factory=list)
    progress: dict[str, MigrationProgress] = field(default_factory=dict)
    checkpoints: dict[str, MigrationCheckpoint] = field(default_factory=dict)
    paused_event: asyncio.Event | None = None
    stop_requested: bool = False
    error_message: str | None = None
    project_id: str | None = None
    executor: str = "go"
    dispatch_config: dict[str, Any] | None = None
    idempotent_writes: bool = False
    validate_after: bool = True
    snapshot_ref: str | None = None
    finalize_after: bool = True
    finalize_options: dict[str, Any] | None = None
    column_type_overrides: dict[str, Any] = field(default_factory=dict)
    procedural_migration: dict[str, Any] | None = None
    source_throttle: Any | None = None
    logs: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class DataExtractor:
    def __init__(self, connector: Any):
        self._connector = connector

    async def extract_range(
        self,
        schema: str,
        table: str,
        columns: list[str],
        column_name: str,
        start: Any,
        end: Any,
        order_column: str | None = None,
    ) -> list[dict[str, Any]]:
        _validate_identifier(schema, "schema")
        _validate_identifier(table, "table")
        _validate_identifier(column_name, "column_name")
        for col in columns:
            _validate_identifier(col, f"column {col!r}")
        if order_column is not None:
            _validate_identifier(order_column, "order_column")
        col_list = ", ".join(f"[{c}]" for c in columns)
        order = order_column or column_name
        # Fix 1.1: Use inclusive upper bound (<= ?) to match the inclusive ChunkBoundary.end.
        # The old `< ?` query missed the last row when chunk_end == max_val.
        # Fix 9.1: MAXDOP is now taken from caller context (default 1).
        query = (
            f"SELECT {col_list} FROM [{schema}].[{table}] "
            f"WHERE [{column_name}] >= ? AND [{column_name}] <= ? "
            f"ORDER BY [{order}] "
            f"OPTION (MAXDOP 1)"
        )
        return await self._connector.execute(query, {"start": start, "end": end})

    async def extract_range_with_hint(
        self,
        schema: str,
        table: str,
        columns: list[str],
        column_name: str,
        start: Any,
        end: Any,
        order_column: str | None = None,
        use_nolock: bool = False,
        maxdop: int = 1,
    ) -> list[dict[str, Any]]:
        _validate_identifier(schema, "schema")
        _validate_identifier(table, "table")
        _validate_identifier(column_name, "column_name")
        for col in columns:
            _validate_identifier(col, f"column {col!r}")
        if order_column is not None:
            _validate_identifier(order_column, "order_column")
        col_list = ", ".join(f"[{c}]" for c in columns)
        order = order_column or column_name
        hint = " WITH (NOLOCK)" if use_nolock else ""
        # Fix 1.1: inclusive upper bound; Fix 9.1: configurable MAXDOP
        query = (
            f"SELECT {col_list} FROM [{schema}].[{table}]{hint} "
            f"WHERE [{column_name}] >= ? AND [{column_name}] <= ? "
            f"ORDER BY [{order}] "
            f"OPTION (MAXDOP {maxdop})"
        )
        return await self._connector.execute(query, {"start": start, "end": end})


class DataLoader:
    def __init__(self, connector: Any, idempotent: bool = False, conflict_columns: list[str] | None = None):
        self._connector = connector
        self._idempotent = idempotent
        self._conflict_columns = conflict_columns

    async def load_chunk(
        self,
        schema: str,
        table: str,
        columns: list[str],
        rows: list[tuple],
        idempotent: bool | None = None,
        conflict_columns: list[str] | None = None,
    ) -> int:
        if not rows:
            return 0
        use_idempotent = idempotent if idempotent is not None else self._idempotent
        use_conflict = conflict_columns or self._conflict_columns
        if use_idempotent and hasattr(self._connector, "copy_with_idempotent_write"):
            return await self._connector.copy_with_idempotent_write(
                table=table,
                columns=columns,
                rows=rows,
                schema=schema if schema else None,
                conflict_columns=use_conflict,
            )
        if hasattr(self._connector, "copy_from_rows"):
            return await self._connector.copy_from_rows(
                table=table,
                columns=columns,
                rows=rows,
                schema=schema if schema else None,
            )
        return 0


class ChunkedMigration:
    def __init__(
        self,
        extractor: DataExtractor,
        loader: DataLoader,
        chunk_size: int = CHUNK_SIZE_DEFAULT,
        chunk_store: ChunkStore | None = None,
        chunk_planner: ChunkPlanner | None = None,
        idempotent_writes: bool = False,
        conflict_columns: list[str] | None = None,
        worker_id: str | None = None,
        lease_duration_sec: int = 60,
        heartbeat_interval_sec: int = 15,
        checkpoint_store: "MigrationCheckpointStore | None" = None,
    ):
        self._extractor = extractor
        self._loader = loader
        self._chunk_size = chunk_size
        self._chunk_store = chunk_store
        self._chunk_planner = chunk_planner
        self._idempotent_writes = idempotent_writes
        self._conflict_columns = conflict_columns
        self._worker_id = worker_id or f"worker-{uuid4().hex[:8]}"
        self._lease_duration_sec = lease_duration_sec
        self._heartbeat_interval_sec = heartbeat_interval_sec
        self._checkpoint_store: "MigrationCheckpointStore | None" = checkpoint_store
        self._progress_callback: Callable[[MigrationProgress], Awaitable[None]] | None = None
        self._paused_event: asyncio.Event | None = None
        self._stop_requested: bool = False
        self._use_nolock: bool = False
        self._latency_tracker: LatencyTracker = LatencyTracker()

    def set_progress_callback(
        self, callback: Callable[[MigrationProgress], Awaitable[None]]
    ) -> None:
        self._progress_callback = callback

    def enable_nolock(self, enabled: bool = True) -> None:
        self._use_nolock = enabled

    async def migrate_table(
        self,
        plan: TableMigrationPlan,
    ) -> TableMigrationResult:
        start_time = datetime.now(UTC)
        result = TableMigrationResult(
            table_name=plan.table_name,
            schema_name=plan.schema_name,
            rows_migrated=0,
            chunks=[],
            status=MigrationStatus.RUNNING,
            start_time=start_time,
        )

        total_rows = 0
        chunk_idx = 0
        chunk_plans: list[ChunkPlan] = []

        if self._chunk_planner:
            chunking_result = await self._chunk_planner.plan_table(
                schema=plan.schema_name,
                table=plan.table_name,
                columns=plan.columns,
            )
            chunk_plans = chunking_result.chunks
            plan.row_count_estimate = chunking_result.total_rows_estimate
            if not chunk_plans:
                logger.info("No chunks generated for table", table=plan.table_name)
                result.status = MigrationStatus.COMPLETED
                result.end_time = datetime.now(UTC)
                return result

            if self._chunk_store and not await self._chunk_store.get_pending_chunks(
                plan.schema_name, plan.table_name
            ):
                await self._chunk_store.save_chunks_batch(chunk_plans)

        if not chunk_plans:
            logger.error(
                "No chunk planner available — cannot migrate table",
                table=plan.table_name,
            )
            result.status = MigrationStatus.FAILED
            result.error = "No chunk planner configured. ChunkPlanner is required."
            result.end_time = datetime.now(UTC)
            return result

        if self._chunk_store:
            logger.info(
                "Expiring stale leases before migration",
                worker=self._worker_id,
                table=plan.table_name,
            )
            await self._chunk_store.expire_stale_leases()

        # 1.4 / 1.7: restore checkpoint from durable store so restarts don't
        # lose both progress counters and the adapted chunk size.
        saved_checkpoint: MigrationCheckpoint | None = None
        if self._checkpoint_store:
            saved_checkpoint = await self._checkpoint_store.load_checkpoint(plan.table_name)
            if saved_checkpoint:
                logger.info(
                    "Resuming from checkpoint",
                    table=plan.table_name,
                    last_chunk=saved_checkpoint.last_chunk_id,
                    rows_done=saved_checkpoint.total_rows_migrated,
                )

        current_chunk_size = (
            saved_checkpoint.adapted_chunk_size
            if saved_checkpoint is not None
            else (plan.chunk_size or self._chunk_size)
        )

        direct_chunk_idx = 0
        try:
            set_active_workers(1)
            while True:
                    if self._stop_requested:
                        result.status = MigrationStatus.STOPPED
                        result.end_time = datetime.now(UTC)
                        return result
                    if self._paused_event:
                        await self._paused_event.wait()

                    if self._chunk_store:
                        chunk_plan = await self._chunk_store.claim_chunk(
                            self._worker_id, plan.schema_name, plan.table_name
                        )
                        if chunk_plan is None:
                            logger.info(
                                "No more chunks to claim",
                                table=plan.table_name,
                            )
                            break
                    else:
                        if direct_chunk_idx >= len(chunk_plans):
                            break
                        chunk_plan = chunk_plans[direct_chunk_idx]
                        direct_chunk_idx += 1

                    heartbeat_task = asyncio.create_task(
                        self._run_heartbeat(str(chunk_plan.chunk_id))
                    )

                    chunk_start = datetime.now(UTC)
                    success = False
                    error: str | None = None
                    rows_in_chunk = 0
                    fetch_duration = 0.0

                    for attempt in range(chunk_plan.max_retries + 1):
                        if attempt > 0:
                            delay = RETRY_DELAYS_SEC[min(attempt - 1, len(RETRY_DELAYS_SEC) - 1)]
                            logger.info(
                                "Retrying chunk",
                                table=plan.table_name,
                                attempt=attempt,
                                delay_sec=delay,
                            )
                            await asyncio.sleep(delay)

                        try:
                            self._latency_tracker.start_source_query(plan.table_name)
                            fetch_start = time.perf_counter()
                            if self._use_nolock:
                                rows = await self._extractor.extract_range_with_hint(
                                    schema=plan.schema_name,
                                    table=plan.table_name,
                                    columns=plan.columns,
                                    column_name=chunk_plan.column_name,
                                    start=chunk_plan.boundary.start,
                                    end=chunk_plan.boundary.end,
                                    use_nolock=True,
                                )
                            else:
                                rows = await self._extractor.extract_range(
                                    schema=plan.schema_name,
                                    table=plan.table_name,
                                    columns=plan.columns,
                                    column_name=chunk_plan.column_name,
                                    start=chunk_plan.boundary.start,
                                    end=chunk_plan.boundary.end,
                                )
                            fetch_end = time.perf_counter()
                            fetch_duration = fetch_end - fetch_start
                            self._latency_tracker.end_source_query(plan.table_name)

                            if not rows:
                                success = True
                                break

                            self._latency_tracker.start_target_write(plan.table_name)
                            from domains.migration.column_transforms import build_pipeline_for_plan

                            transform_pipeline = build_pipeline_for_plan(
                                column_transforms=plan.column_transforms,
                                column_sensitivity=plan.column_sensitivity,
                                column_types=plan.column_types,
                            )
                            if transform_pipeline:
                                rows = transform_pipeline.apply_batch(rows)
                            row_tuples = [tuple(r.values()) for r in rows]
                            inserted = await self._loader.load_chunk(
                                schema=plan.target_schema,   # Fix 1.2: use plan field, not "public"
                                table=plan.table_name,
                                columns=plan.columns,
                                rows=row_tuples,
                                idempotent=self._idempotent_writes,
                                conflict_columns=self._conflict_columns,
                            )
                            self._latency_tracker.end_target_write(plan.table_name)

                            rows_in_chunk = inserted
                            success = True
                            break

                        except Exception as e:
                            error = str(e)
                            logger.warning(
                                "Chunk attempt failed",
                                table=plan.table_name,
                                attempt=attempt,
                                error=str(e),
                            )

                    heartbeat_task.cancel()
                    try:
                        await heartbeat_task
                    except asyncio.CancelledError:
                        pass

                    if not success:
                        record_failure(plan.table_name)
                        if chunk_plan.retry_count >= chunk_plan.max_retries - 1:
                            await self._update_chunk_status(chunk_plan, ChunkStatus.QUARANTINED, error)
                        else:
                            chunk_plan.retry_count += 1
                            await self._update_chunk_status(chunk_plan, ChunkStatus.FAILED, error)
                        if self._chunk_store:
                            await self._chunk_store.release_chunk(
                                str(chunk_plan.chunk_id), self._worker_id
                            )
                        result.status = MigrationStatus.FAILED
                        result.error = error
                        result.end_time = datetime.now(UTC)
                        return result

                    if rows_in_chunk == 0:
                        await self._update_chunk_status(chunk_plan, ChunkStatus.COMPLETED)
                        if self._chunk_store:
                            await self._chunk_store.release_chunk(
                                str(chunk_plan.chunk_id), self._worker_id
                            )
                        continue

                    chunk_end = datetime.now(UTC)
                    chunk_result = ChunkResult(
                        chunk_id=chunk_idx,
                        rows_migrated=rows_in_chunk,
                        start_time=chunk_start,
                        end_time=chunk_end,
                        success=True,
                    )
                    result.chunks.append(chunk_result)
                    total_rows += rows_in_chunk
                    chunk_idx += 1

                    chunk_plan.fetch_duration_ms = fetch_duration * 1000
                    chunk_plan.rows_migrated = rows_in_chunk
                    await self._update_chunk_status(chunk_plan, ChunkStatus.COMPLETED)
                    if self._chunk_store:
                        await self._chunk_store.release_chunk(
                            str(chunk_plan.chunk_id), self._worker_id
                        )

                    record_rows_migrated(plan.table_name, rows_in_chunk)
                    record_chunk_duration(fetch_duration * 1000)

                    current_chunk_size = self._adapt_chunk_size(
                        current_chunk_size, fetch_duration, plan.row_count_estimate, total_rows
                    )

                    # 1.4 / 1.7: persist checkpoint (with adapted chunk size) after every chunk
                    if self._checkpoint_store:
                        cp = MigrationCheckpoint(
                            table_name=plan.table_name,
                            last_chunk_id=chunk_idx,
                            last_offset=total_rows,
                            total_rows_migrated=total_rows,
                            status=MigrationStatus.RUNNING,
                            adapted_chunk_size=current_chunk_size,
                        )
                        await self._checkpoint_store.save_checkpoint(cp)

                    if self._progress_callback:
                        progress = self._build_progress(plan, total_rows, chunk_idx, chunk_idx + 1, start_time)
                        await self._progress_callback(progress)

            end_time = datetime.now(UTC)
            duration = (end_time - start_time).total_seconds()
            result.rows_migrated = total_rows
            result.status = MigrationStatus.COMPLETED
            result.end_time = end_time
            result.total_duration_seconds = duration
            result.throughput_rows_per_sec = total_rows / duration if duration > 0 else 0

            logger.info(
                "Table migration completed",
                table=plan.table_name,
                rows_migrated=total_rows,
                duration_seconds=round(duration, 2),
            )

        except Exception as e:
            logger.error(
                "Table migration failed",
                table=plan.table_name,
                error=str(e),
                rows_migrated=total_rows,
            )
            result.status = MigrationStatus.FAILED
            result.error = str(e)
            result.end_time = datetime.now(UTC)
            record_failure(plan.table_name)
        finally:
            set_active_workers(0)

        return result

    async def _run_heartbeat(self, chunk_id: str) -> None:
        while True:
            await asyncio.sleep(self._heartbeat_interval_sec)
            if not self._chunk_store:
                return
            renewed = await self._chunk_store.renew_lease(chunk_id, self._worker_id)
            if not renewed:
                logger.warning(
                    "Lease renewal failed — lost claim on chunk",
                    chunk_id=chunk_id,
                    worker=self._worker_id,
                )
                return

    @staticmethod
    def _adapt_chunk_size(
        current_size: int, fetch_duration: float, total_estimate: int, rows_done: int
    ) -> int:
        if fetch_duration < FETCH_TIME_FAST_SEC:
            new_size = min(int(current_size * 1.5), CHUNK_SIZE_MAX)
            if new_size != current_size:
                logger.debug("Increasing chunk size", old=current_size, new=new_size, reason="fast_fetch")
            return new_size
        elif fetch_duration > FETCH_TIME_SLOW_SEC:
            new_size = max(int(current_size // 2), CHUNK_SIZE_MIN)
            if new_size != current_size:
                logger.debug("Decreasing chunk size", old=current_size, new=new_size, reason="slow_fetch")
            return new_size
        return current_size

    async def _update_chunk_status(
        self, chunk_plan: ChunkPlan, status: ChunkStatus, error: str | None = None
    ) -> None:
        chunk_plan.status = status
        if error:
            chunk_plan.error = error
        if self._chunk_store:
            await self._chunk_store.update_status(str(chunk_plan.chunk_id), status, error)
            if status == ChunkStatus.COMPLETED:
                await self._chunk_store.save_chunk(chunk_plan)

    def _build_progress(
        self,
        plan: TableMigrationPlan,
        total_rows: int,
        current_chunk: int,
        total_chunks: int,
        start_time: datetime,
    ) -> MigrationProgress:
        elapsed = (datetime.now(UTC) - start_time).total_seconds()
        throughput = total_rows / elapsed if elapsed > 0 else 0
        remaining_rows = max(0, plan.row_count_estimate - total_rows)
        eta = remaining_rows / throughput if throughput > 0 else 0
        pct = ((total_rows / plan.row_count_estimate) * 100) if plan.row_count_estimate > 0 else 0

        return MigrationProgress(
            table_name=plan.table_name,
            schema_name=plan.schema_name,
            total_rows_estimate=plan.row_count_estimate,
            rows_migrated=total_rows,
            percentage=min(pct, 100),
            current_chunk=current_chunk,
            total_chunks=max(1, total_chunks),
            status=MigrationStatus.RUNNING,
            throughput_rows_per_sec=throughput,
            elapsed_seconds=elapsed,
            estimated_remaining_seconds=eta,
        )

    def _load_checkpoint(self, table_name: str) -> MigrationCheckpoint | None:
        """Legacy in-memory fallback — use MigrationCheckpointStore for durable persistence."""
        if hasattr(self, "_checkpoints") and self._checkpoints:
            return self._checkpoints.get(table_name)
        return None

    def _save_checkpoint(self, table_name: str, checkpoint: MigrationCheckpoint) -> None:
        """Legacy in-memory fallback — use MigrationCheckpointStore for durable persistence."""
        if not hasattr(self, "_checkpoints"):
            self._checkpoints: dict[str, MigrationCheckpoint] = {}
        self._checkpoints[table_name] = checkpoint
