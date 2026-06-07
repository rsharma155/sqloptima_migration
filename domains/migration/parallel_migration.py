"""
Module: parallel_migration.py
Purpose: Chunked data migration engine
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from domains.chunking.chunk_planner import ChunkPlanner
from domains.migration.migration_engine import (
    ChunkResult,
    DataExtractor,
    DataLoader,
    MigrationStatus,
    TableMigrationPlan,
    TableMigrationResult,
    logger,
)
from domains.migration.migration_engine import RETRY_DELAYS_SEC
from shared.kernel.sql_identifier import validate_sql_identifier


@dataclass
class PartitionRange:
    partition_id: int
    start_value: Any
    end_value: Any
    worker_id: int = 0


@dataclass
class WorkerResult:
    worker_id: int
    partition_id: int
    rows_migrated: int
    chunks: list[ChunkResult]
    success: bool
    error: str | None = None


class PartitionStrategy:
    @staticmethod
    async def compute_ranges(
        connector: Any,
        schema: str,
        table: str,
        partition_column: str,
        num_partitions: int,
    ) -> list[PartitionRange]:
        validate_sql_identifier(schema, "schema")
        validate_sql_identifier(table, "table")
        validate_sql_identifier(partition_column, "partition_column")
        if not isinstance(num_partitions, int) or num_partitions < 1:
            raise ValueError(f"num_partitions must be a positive integer, got {num_partitions!r}")
        # Fix 8.3: bracket-quote all SQL Server identifiers to handle reserved words and spaces.
        query = f"""
        SELECT min_val, max_val FROM (
            SELECT
                MIN([{partition_column}]) OVER (PARTITION BY ntile) AS min_val,
                MAX([{partition_column}]) OVER (PARTITION BY ntile) AS max_val,
                ntile
            FROM (
                SELECT [{partition_column}],
                       NTILE({num_partitions}) OVER (ORDER BY [{partition_column}]) AS ntile
                FROM [{schema}].[{table}]
            ) t
        ) sub
        GROUP BY ntile, min_val, max_val
        ORDER BY ntile
        """
        rows = await connector.execute(query)
        return [
            PartitionRange(partition_id=i, start_value=r["min_val"], end_value=r["max_val"])
            for i, r in enumerate(rows)
        ]

    @staticmethod
    async def compute_deterministic_ranges(
        connector: Any,
        schema: str,
        table: str,
        column_name: str,
        chunk_size: int,
        max_partitions: int = 8,
    ) -> list[PartitionRange]:
        planner = ChunkPlanner(connector, chunk_size=chunk_size)
        chunking_result = await planner.plan_table(schema, table)
        if not chunking_result.chunks:
            return []

        chunks_per_partition = max(1, len(chunking_result.chunks) // max_partitions)
        partitions: list[PartitionRange] = []
        for i in range(0, len(chunking_result.chunks), chunks_per_partition):
            group = chunking_result.chunks[i:i + chunks_per_partition]
            partitions.append(PartitionRange(
                partition_id=len(partitions),
                start_value=group[0].boundary.start if group[0].boundary else 0,
                end_value=group[-1].boundary.end if group[-1].boundary else 0,
            ))
        return partitions

    @staticmethod
    async def compute_id_ranges(
        connector: Any,
        schema: str,
        table: str,
        partition_column: str,
        chunk_size: int,
    ) -> list[PartitionRange]:
        validate_sql_identifier(schema, "schema")
        validate_sql_identifier(table, "table")
        # Fix 8.3: bracket-quote schema and table.
        count_query = f"SELECT COUNT(*) AS cnt FROM [{schema}].[{table}]"
        result = await connector.execute(count_query)
        total = result[0]["cnt"] if result else 0
        if total == 0:
            return []

        num_chunks = max(1, (total + chunk_size - 1) // chunk_size)
        return [
            PartitionRange(
                partition_id=i,
                start_value=i * chunk_size,
                end_value=(i + 1) * chunk_size,
            )
            for i in range(num_chunks)
        ]


class ParallelMigration:
    def __init__(
        self,
        extractor: DataExtractor,
        loader: DataLoader,
        max_workers: int = 4,
        connector_factory: Any = None,
    ):
        self._extractor = extractor
        self._loader = loader
        self._max_workers = max_workers
        # Fix 1.9: each parallel worker gets its own connector via this factory.
        # When None, legacy mode (shared extractor connector) is preserved.
        self._connector_factory = connector_factory
        self._paused = asyncio.Event()
        self._paused.set()
        self._stopped = False
        self._use_nolock: bool = False

    def enable_nolock(self, enabled: bool = True) -> None:
        self._use_nolock = enabled

    async def migrate_table(
        self,
        plan: TableMigrationPlan,
        partition_column: str,
        num_workers: int | None = None,
    ) -> TableMigrationResult:
        num_workers = num_workers or min(plan.parallel_workers, self._max_workers)
        start_time = datetime.now(UTC)

        result = TableMigrationResult(
            table_name=plan.table_name,
            schema_name=plan.schema_name,
            rows_migrated=0,
            chunks=[],
            status=MigrationStatus.RUNNING,
            start_time=start_time,
        )

        try:
            ranges = await PartitionStrategy.compute_deterministic_ranges(
                self._extractor._connector,
                plan.schema_name,
                plan.table_name,
                partition_column,
                plan.chunk_size,
                max_partitions=num_workers,
            )

            if not ranges:
                ranges = await PartitionStrategy.compute_id_ranges(
                    self._extractor._connector,
                    plan.schema_name,
                    plan.table_name,
                    partition_column,
                    plan.chunk_size,
                )

            if not ranges:
                result.status = MigrationStatus.COMPLETED
                result.end_time = datetime.now(UTC)
                return result

            semaphore = asyncio.Semaphore(num_workers)
            total_rows = 0
            all_chunks: list[ChunkResult] = []

            async def _worker(pr: PartitionRange) -> WorkerResult:
                async with semaphore:
                    return await self._migrate_partition(plan, pr)

            tasks = [_worker(pr) for pr in ranges]
            worker_results = await asyncio.gather(*tasks, return_exceptions=True)

            for wr in worker_results:
                if isinstance(wr, Exception):
                    result.status = MigrationStatus.FAILED
                    result.error = str(wr)
                elif isinstance(wr, WorkerResult):
                    total_rows += wr.rows_migrated
                    all_chunks.extend(wr.chunks)
                    if not wr.success and result.error is None:
                        result.error = wr.error
                        result.status = MigrationStatus.FAILED

            end_time = datetime.now(UTC)
            duration = (end_time - start_time).total_seconds()
            result.rows_migrated = total_rows
            result.chunks = all_chunks

            if result.status != MigrationStatus.FAILED:
                result.status = MigrationStatus.COMPLETED

            result.end_time = end_time
            result.total_duration_seconds = duration
            result.throughput_rows_per_sec = total_rows / duration if duration > 0 else 0

        except Exception as e:
            result.status = MigrationStatus.FAILED
            result.error = str(e)
            result.end_time = datetime.now(UTC)

        return result

    def pause(self):
        self._paused.clear()

    def resume(self):
        self._paused.set()

    def stop(self):
        self._stopped = True
        self._paused.set()

    async def migrate_with_ranges(
        self,
        plan: TableMigrationPlan,
        ranges: list[PartitionRange],
        num_workers: int | None = None,
    ) -> TableMigrationResult:
        """Fix 1.9: like migrate_table but accepts pre-computed ranges.

        When ``connector_factory`` was provided each worker gets its own
        freshly connected SqlServerConnector instead of sharing the extractor's
        single connection.
        """
        num_workers = num_workers or self._max_workers
        from datetime import UTC, datetime as _dt

        start_time = _dt.now(UTC)
        result = TableMigrationResult(
            table_name=plan.table_name,
            schema_name=plan.schema_name,
            rows_migrated=0,
            chunks=[],
            status=MigrationStatus.RUNNING,
            start_time=start_time,
        )

        if not ranges:
            result.status = MigrationStatus.COMPLETED
            result.end_time = _dt.now(UTC)
            return result

        semaphore = asyncio.Semaphore(num_workers)
        total_rows = 0
        all_chunks: list[ChunkResult] = []

        async def _worker(pr: PartitionRange) -> WorkerResult:
            async with semaphore:
                own_connector = None
                if self._connector_factory is not None:
                    own_connector = self._connector_factory()
                    await own_connector.connect()
                try:
                    return await self._migrate_partition(plan, pr, connector=own_connector)
                finally:
                    if own_connector is not None:
                        await own_connector.disconnect()

        tasks = [_worker(pr) for pr in ranges]
        worker_results = await asyncio.gather(*tasks, return_exceptions=True)

        for wr in worker_results:
            if isinstance(wr, Exception):
                result.status = MigrationStatus.FAILED
                result.error = str(wr)
            elif isinstance(wr, WorkerResult):
                total_rows += wr.rows_migrated
                all_chunks.extend(wr.chunks)
                if not wr.success and result.error is None:
                    result.error = wr.error
                    result.status = MigrationStatus.FAILED

        end_time = _dt.now(UTC)
        duration = (end_time - start_time).total_seconds()
        result.rows_migrated = total_rows
        result.chunks = all_chunks
        if result.status != MigrationStatus.FAILED:
            result.status = MigrationStatus.COMPLETED
        result.end_time = end_time
        result.total_duration_seconds = duration
        result.throughput_rows_per_sec = total_rows / duration if duration > 0 else 0
        return result

    async def _migrate_partition(
        self,
        plan: TableMigrationPlan,
        partition: PartitionRange,
        connector: Any = None,
    ) -> WorkerResult:
        wr = WorkerResult(
            worker_id=partition.worker_id,
            partition_id=partition.partition_id,
            rows_migrated=0,
            chunks=[],
            success=True,
        )

        column_name = plan.order_column or "id"
        current_start = partition.start_value

        try:
            while current_start < partition.end_value:
                if self._stopped:
                    wr.success = False
                    wr.error = "Migration stopped"
                    return wr
                await self._paused.wait()

                next_end = min(
                    current_start + plan.chunk_size,
                    partition.end_value,
                )

                for attempt in range(4):
                    try:
                        if self._use_nolock:
                            rows = await self._extractor.extract_range_with_hint(
                                schema=plan.schema_name,
                                table=plan.table_name,
                                columns=plan.columns,
                                column_name=column_name,
                                start=current_start,
                                end=next_end,
                                use_nolock=True,
                            )
                        else:
                            rows = await self._extractor.extract_range(
                                schema=plan.schema_name,
                                table=plan.table_name,
                                columns=plan.columns,
                                column_name=column_name,
                                start=current_start,
                                end=next_end,
                            )
                        break
                    except Exception as e:
                        if attempt < 3:
                            delay = RETRY_DELAYS_SEC[attempt]
                            await asyncio.sleep(delay)
                        else:
                            raise

                if not rows:
                    break

                row_tuples = [tuple(r.values()) for r in rows]
                inserted = await self._loader.load_chunk(
                    schema=plan.target_schema,   # Fix 1.2: use plan.target_schema
                    table=plan.table_name,
                    columns=plan.columns,
                    rows=row_tuples,
                )

                chunk = ChunkResult(
                    chunk_id=len(wr.chunks),
                    rows_migrated=inserted,
                    start_time=datetime.now(UTC),
                    end_time=datetime.now(UTC),
                    success=True,
                )
                wr.chunks.append(chunk)
                wr.rows_migrated += inserted
                current_start = next_end

            logger.info(
                "Partition migrated",
                table=plan.table_name,
                partition=partition.partition_id,
                rows_migrated=wr.rows_migrated,
            )

        except Exception as e:
            wr.success = False
            wr.error = str(e)
            logger.error(
                "Partition migration failed",
                table=plan.table_name,
                partition=partition.partition_id,
                error=str(e),
            )

        return wr
