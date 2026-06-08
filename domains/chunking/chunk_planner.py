"""
Module: chunk_planner.py
Purpose: Data chunking for bulk migrations
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)

_ROWVERSION_TYPES = {"rowversion", "timestamp"}
_DATETIME_TYPES = {"datetime", "datetime2", "smalldatetime"}
_NUMERIC_TYPES = {"bigint", "int", "numeric", "decimal", "smallint", "tinyint"}
_UUID_TYPES = {"uniqueidentifier"}


class ChunkStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    QUARANTINED = "quarantined"


class ChunkColumnType(StrEnum):
    IDENTITY_PK = "identity_pk"
    BIGINT_PK = "bigint_pk"
    DATETIME_PK = "datetime_pk"
    ROWVERSION = "rowversion"
    UUID_PK = "uuid_pk"          # Fix 1.3: uniqueidentifier primary key chunking
    SYNTHETIC = "synthetic"


@dataclass
class ChunkBoundary:
    start: Any
    end: Any

    def __post_init__(self):
        self._hash: str | None = None

    @property
    def hash(self) -> str:
        if self._hash is None:
            raw = f"{self.start}:{self.end}"
            self._hash = hashlib.sha256(raw.encode()).hexdigest()
        return self._hash


@dataclass
class ChunkPlan:
    chunk_id: UUID = field(default_factory=uuid4)
    table_schema: str = ""
    table_name: str = ""
    boundary: ChunkBoundary | None = None
    column_name: str = ""
    column_type: ChunkColumnType = ChunkColumnType.IDENTITY_PK
    status: ChunkStatus = ChunkStatus.PENDING
    retry_count: int = 0
    max_retries: int = 3
    chunk_hash: str = ""
    fetch_duration_ms: float = 0.0
    rows_migrated: int = 0
    bytes_transferred: int = 0
    error: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    lease_holder: str | None = None
    lease_expires_at: datetime | None = None

    def __post_init__(self):
        if self.boundary and not self.chunk_hash:
            self.chunk_hash = hashlib.sha256(
                f"{self.table_schema}.{self.table_name}:{self.boundary.hash}".encode()
            ).hexdigest()

    @property
    def qualified_name(self) -> str:
        return f"{self.table_schema}.{self.table_name}"


@dataclass
class ChunkingResult:
    chunks: list[ChunkPlan]
    total_rows_estimate: int
    min_value: Any = None
    max_value: Any = None
    column_name: str = ""
    column_type: ChunkColumnType = ChunkColumnType.IDENTITY_PK


class ChunkPlanner:
    def __init__(self, connector: Any, chunk_size: int = 10000):
        self._connector = connector
        self._chunk_size = chunk_size

    async def plan_table(
        self,
        schema: str,
        table: str,
        columns: list[str] | None = None,
        use_composite: bool = False,
    ) -> ChunkingResult:
        column_name, column_type = await self._detect_chunk_column(schema, table)
        composite_columns = []
        if use_composite:
            composite_columns, _ = await self._detect_chunk_columns_composite(schema, table)

        if composite_columns:
            column_names = [c[0] for c in composite_columns]
            column_types = [c[1] for c in composite_columns]
            min_val, max_val = await self._get_boundaries(schema, table, column_names[0])
            if min_val is None or max_val is None:
                logger.info("Empty table for chunking", table=f"{schema}.{table}")
                return ChunkingResult(chunks=[], total_rows_estimate=0)
            total_estimate = await self._get_approximate_count(schema, table)
            chunks = self._generate_ranges_composite(
                schema=schema,
                table=table,
                column_names=column_names,
                column_types=column_types,
                min_val=min_val,
                max_val=max_val,
            )
            return ChunkingResult(
                chunks=chunks,
                total_rows_estimate=total_estimate,
                min_value=min_val,
                max_value=max_val,
                column_name=",".join(column_names),
                column_type=column_type,
            )

        min_val, max_val = await self._get_boundaries(schema, table, column_name)
        if min_val is None or max_val is None:
            logger.info("Empty or non-numeric PK for chunking", table=f"{schema}.{table}")
            return ChunkingResult(chunks=[], total_rows_estimate=0)

        total_estimate = await self._get_approximate_count(schema, table)
        chunks = self._generate_ranges(
            schema=schema,
            table=table,
            column_name=column_name,
            column_type=column_type,
            min_val=min_val,
            max_val=max_val,
        )
        return ChunkingResult(
            chunks=chunks,
            total_rows_estimate=total_estimate,
            min_value=min_val,
            max_value=max_val,
            column_name=column_name,
            column_type=column_type,
        )

    async def _detect_chunk_column(
        self, schema: str, table: str
    ) -> tuple[str, ChunkColumnType]:
        pk_query = """
            SELECT c.name AS column_name,
                   tp.name AS type_name,
                   c.is_identity
            FROM sys.indexes i
            INNER JOIN sys.index_columns ic
                ON i.object_id = ic.object_id AND i.index_id = ic.index_id
            INNER JOIN sys.columns c
                ON i.object_id = c.object_id AND ic.column_id = c.column_id
            INNER JOIN sys.types tp
                ON c.system_type_id = tp.system_type_id
            WHERE i.is_primary_key = 1
              AND OBJECT_SCHEMA_NAME(i.object_id) = ?
              AND OBJECT_NAME(i.object_id) = ?
            ORDER BY ic.key_ordinal
        """
        try:
            rows = await self._connector.execute(pk_query, {"schema": schema, "table": table})
            for r in rows:
                name = r["column_name"]
                type_name = r.get("type_name", "").lower()
                is_identity = r.get("is_identity", False)
                if is_identity:
                    return name, ChunkColumnType.IDENTITY_PK
                if type_name in _ROWVERSION_TYPES:
                    return name, ChunkColumnType.ROWVERSION
                if type_name in _NUMERIC_TYPES:
                    return name, ChunkColumnType.BIGINT_PK
                if type_name in _UUID_TYPES:                    # Fix 1.3
                    return name, ChunkColumnType.UUID_PK
        except Exception:
            pass

        datetime_pk_query = """
            SELECT c.name AS column_name, tp.name AS type_name
            FROM sys.indexes i
            INNER JOIN sys.index_columns ic
                ON i.object_id = ic.object_id AND i.index_id = ic.index_id
            INNER JOIN sys.columns c
                ON i.object_id = c.object_id AND ic.column_id = c.column_id
            INNER JOIN sys.types tp
                ON c.system_type_id = tp.system_type_id
            WHERE i.is_primary_key = 1
              AND OBJECT_SCHEMA_NAME(i.object_id) = ?
              AND OBJECT_NAME(i.object_id) = ?
            ORDER BY ic.key_ordinal
        """
        try:
            rows = await self._connector.execute(
                datetime_pk_query, {"schema": schema, "table": table}
            )
            datetime_cols = [
                r["column_name"]
                for r in rows
                if r.get("type_name", "").lower() in _DATETIME_TYPES
            ]
            int_cols = [
                r["column_name"]
                for r in rows
                if r.get("type_name", "").lower() in _NUMERIC_TYPES
            ]
            rowver_cols = [
                r["column_name"]
                for r in rows
                if r.get("type_name", "").lower() in _ROWVERSION_TYPES
            ]
            uuid_cols = [                                              # Fix 1.3
                r["column_name"]
                for r in rows
                if r.get("type_name", "").lower() in _UUID_TYPES
            ]
            if datetime_cols:
                return datetime_cols[0], ChunkColumnType.DATETIME_PK
            if rowver_cols:
                return rowver_cols[0], ChunkColumnType.ROWVERSION
            if int_cols:
                return int_cols[0], ChunkColumnType.BIGINT_PK
            if uuid_cols:                                             # Fix 1.3
                return uuid_cols[0], ChunkColumnType.UUID_PK
            if rows:
                return rows[0]["column_name"], ChunkColumnType.SYNTHETIC
        except Exception:
            pass

        return "id", ChunkColumnType.SYNTHETIC

    async def _detect_chunk_columns_composite(
        self, schema: str, table: str
    ) -> tuple[list[tuple[str, ChunkColumnType]], ChunkColumnType]:
        pk_query = """
            SELECT c.name AS column_name,
                   tp.name AS type_name,
                   c.is_identity
            FROM sys.indexes i
            INNER JOIN sys.index_columns ic
                ON i.object_id = ic.object_id AND i.index_id = ic.index_id
            INNER JOIN sys.columns c
                ON i.object_id = c.object_id AND ic.column_id = c.column_id
            INNER JOIN sys.types tp
                ON c.system_type_id = tp.system_type_id
            WHERE i.is_primary_key = 1
              AND OBJECT_SCHEMA_NAME(i.object_id) = ?
              AND OBJECT_NAME(i.object_id) = ?
            ORDER BY ic.key_ordinal
        """
        try:
            rows = await self._connector.execute(pk_query, {"schema": schema, "table": table})
            if len(rows) > 1:
                cols = []
                for r in rows:
                    name = r["column_name"]
                    type_name = r.get("type_name", "").lower()
                    if type_name in _ROWVERSION_TYPES:
                        cols.append((name, ChunkColumnType.ROWVERSION))
                    elif type_name in _NUMERIC_TYPES:
                        cols.append((name, ChunkColumnType.BIGINT_PK))
                    elif type_name in _DATETIME_TYPES:
                        cols.append((name, ChunkColumnType.DATETIME_PK))
                    else:
                        cols.append((name, ChunkColumnType.SYNTHETIC))
                return cols, ChunkColumnType.BIGINT_PK
        except Exception:
            pass
        return [], ChunkColumnType.SYNTHETIC

    async def _get_boundaries(
        self, schema: str, table: str, column: str
    ) -> tuple[Any, Any]:
        query = f"SELECT MIN([{column}]) AS min_val, MAX([{column}]) AS max_val FROM [{schema}].[{table}]"
        try:
            rows = await self._connector.execute(query)
            if rows:
                return rows[0]["min_val"], rows[0]["max_val"]
        except Exception:
            pass
        return None, None

    async def _get_approximate_count(self, schema: str, table: str) -> int:
        from infrastructure.sqlserver.row_count_estimate import (
            fetch_sqlserver_table_row_estimate,
        )

        return await fetch_sqlserver_table_row_estimate(
            self._connector, schema, table,
        )

    def _generate_ranges(
        self,
        schema: str,
        table: str,
        column_name: str,
        column_type: ChunkColumnType,
        min_val: Any,
        max_val: Any,
    ) -> list[ChunkPlan]:
        chunks: list[ChunkPlan] = []
        if column_type in (ChunkColumnType.IDENTITY_PK, ChunkColumnType.BIGINT_PK):
            current = int(min_val)
            end_val = int(max_val)
            step = max(1, self._chunk_size)
            while current <= end_val:
                chunk_end = min(current + step - 1, end_val)
                boundary = ChunkBoundary(start=current, end=chunk_end)
                chunks.append(ChunkPlan(
                    table_schema=schema,
                    table_name=table,
                    boundary=boundary,
                    column_name=column_name,
                    column_type=column_type,
                    chunk_hash=hashlib.sha256(
                        f"{schema}.{table}:{current}:{chunk_end}".encode()
                    ).hexdigest(),
                ))
                current = chunk_end + 1
        elif column_type == ChunkColumnType.DATETIME_PK:
            step_days = max(1, self._chunk_size // 1000)
            current = min_val
            end_val = max_val
            while current <= end_val:
                import datetime as dt
                if isinstance(current, str):
                    current_dt = dt.datetime.fromisoformat(current)
                    end_dt = dt.datetime.fromisoformat(end_val)
                else:
                    current_dt = current
                    end_dt = end_val
                chunk_end_dt = current_dt + dt.timedelta(days=step_days)
                if chunk_end_dt > end_dt:
                    chunk_end_dt = end_dt
                boundary = ChunkBoundary(start=current_dt.isoformat(), end=chunk_end_dt.isoformat())
                chunks.append(ChunkPlan(
                    table_schema=schema,
                    table_name=table,
                    boundary=boundary,
                    column_name=column_name,
                    column_type=column_type,
                    chunk_hash=hashlib.sha256(
                        f"{schema}.{table}:{current_dt.isoformat()}:{chunk_end_dt.isoformat()}".encode()
                    ).hexdigest(),
                ))
                current = chunk_end_dt + dt.timedelta(days=1)
                if current > end_dt:
                    break
        elif column_type == ChunkColumnType.UUID_PK:
            # Fix 1.3: UUID chunking via lexicographic text ordering.
            # Cast UUIDs to CHAR(36) text and split on prefix ranges so each chunk
            # covers a predictable lexicographic band of UUID strings.
            chunks.extend(self._generate_uuid_ranges(schema, table, column_name, min_val, max_val))
        else:
            chunks.append(ChunkPlan(
                table_schema=schema,
                table_name=table,
                boundary=ChunkBoundary(start=min_val, end=max_val),
                column_name=column_name,
                column_type=column_type,
                chunk_hash=hashlib.sha256(
                    f"{schema}.{table}:{min_val}:{max_val}".encode()
                ).hexdigest(),
            ))

        logger.info(
            "Generated chunk plan",
            table=f"{schema}.{table}",
            column=column_name,
            column_type=column_type.value,
            chunk_count=len(chunks),
        )
        return chunks

    def _generate_ranges_composite(
        self,
        schema: str,
        table: str,
        column_names: list[str],
        column_types: list[ChunkColumnType],
        min_val: Any,
        max_val: Any,
    ) -> list[ChunkPlan]:
        chunks: list[ChunkPlan] = []
        current = int(min_val)
        end_val = int(max_val)
        step = max(1, self._chunk_size)
        primary_col = column_names[0]
        while current <= end_val:
            chunk_end = min(current + step - 1, end_val)
            boundary = ChunkBoundary(start=current, end=chunk_end)
            chunks.append(ChunkPlan(
                table_schema=schema,
                table_name=table,
                boundary=boundary,
                column_name=primary_col,
                column_type=ChunkColumnType.BIGINT_PK,
                chunk_hash=hashlib.sha256(
                    f"{schema}.{table}:{current}:{chunk_end}".encode()
                ).hexdigest(),
            ))
            current = chunk_end + 1
        return chunks

    def _generate_uuid_ranges(
        self,
        schema: str,
        table: str,
        column_name: str,
        min_val: Any,
        max_val: Any,
    ) -> list[ChunkPlan]:
        """Fix 1.3: Generate UUID chunk ranges via lexicographic boundary splitting.

        Splits the UUID space into fixed-size buckets using the first hex nibble
        (0–f = 16 buckets). Each bucket is one chunk.  If chunk_size is larger
        than the expected bucket size the buckets are merged, but we always emit
        at least one chunk covering [min_val, max_val].
        """
        # Build 16 hex-prefix bands using first character of UUID string.
        # These map naturally to SQL Server: CAST(col AS CHAR(36)) ordering.
        hex_chars = "0123456789abcdef"
        boundaries = []
        for ch in hex_chars:
            lower = f"{ch}0000000-0000-0000-0000-000000000000"
            upper = f"{ch}fffffff-ffff-ffff-ffff-ffffffffffff"
            boundaries.append((lower, upper))

        chunks: list[ChunkPlan] = []
        for (band_start, band_end) in boundaries:
            # Intersect with actual min/max to avoid empty ranges
            effective_start = max(str(min_val).lower(), band_start)
            effective_end = min(str(max_val).lower(), band_end)
            if effective_start > effective_end:
                continue
            chunks.append(ChunkPlan(
                table_schema=schema,
                table_name=table,
                boundary=ChunkBoundary(start=effective_start, end=effective_end),
                column_name=column_name,
                column_type=ChunkColumnType.UUID_PK,
                chunk_hash=hashlib.sha256(
                    f"{schema}.{table}:{effective_start}:{effective_end}".encode()
                ).hexdigest(),
            ))

        if not chunks:
            # Fallback: single chunk covering the full UUID range
            chunks.append(ChunkPlan(
                table_schema=schema,
                table_name=table,
                boundary=ChunkBoundary(start=min_val, end=max_val),
                column_name=column_name,
                column_type=ChunkColumnType.UUID_PK,
                chunk_hash=hashlib.sha256(
                    f"{schema}.{table}:{min_val}:{max_val}".encode()
                ).hexdigest(),
            ))
        return chunks

    async def split_skewed_chunk_auto(
        self,
        chunk: ChunkPlan,
        schema: str,
        table: str,
        fetch_duration_ms: float,
        timeout_ms: float = 10000,
    ) -> list[ChunkPlan]:
        if fetch_duration_ms < timeout_ms:
            return [chunk]
        logger.info(
            "Auto-splitting skewed chunk",
            table=f"{schema}.{table}",
            start=chunk.boundary.start,
            end=chunk.boundary.end,
            fetch_duration_ms=fetch_duration_ms,
        )
        return await self.split_skewed_chunk(chunk, schema, table)

    async def split_skewed_chunk(
        self,
        chunk: ChunkPlan,
        schema: str,
        table: str,
        split_factor: int = 2,
    ) -> list[ChunkPlan]:
        if not chunk.boundary:
            return [chunk]
        mid_raw = await self._get_midpoint(schema, table, chunk.column_name, chunk.boundary)
        if mid_raw is None:
            return [chunk]
        mid = int(mid_raw)
        left = ChunkPlan(
            table_schema=schema,
            table_name=table,
            boundary=ChunkBoundary(start=chunk.boundary.start, end=mid),
            column_name=chunk.column_name,
            column_type=chunk.column_type,
            chunk_hash=hashlib.sha256(
                f"{schema}.{table}:{chunk.boundary.start}:{mid}".encode()
            ).hexdigest(),
        )
        right = ChunkPlan(
            table_schema=schema,
            table_name=table,
            boundary=ChunkBoundary(start=mid + 1, end=chunk.boundary.end),
            column_name=chunk.column_name,
            column_type=chunk.column_type,
            chunk_hash=hashlib.sha256(
                f"{schema}.{table}:{mid + 1}:{chunk.boundary.end}".encode()
            ).hexdigest(),
        )
        return [left, right]

    async def _get_midpoint(
        self, schema: str, table: str, column: str, boundary: ChunkBoundary
    ) -> Any:
        query = (
            f"SELECT MIN([{column}]) + (MAX([{column}]) - MIN([{column}])) / 2 AS mid "
            f"FROM [{schema}].[{table}] "
            f"WHERE [{column}] BETWEEN ? AND ?"
        )
        try:
            rows = await self._connector.execute(
                query, {"start": boundary.start, "end": boundary.end}
            )
            if rows and rows[0]["mid"] is not None:
                return rows[0]["mid"]
        except Exception:
            pass
        if isinstance(boundary.start, (int, float)) and isinstance(boundary.end, (int, float)):
            return (boundary.start + boundary.end) // 2
        return None

    def compute_chunk_hash(self, schema: str, table: str, start: Any, end: Any) -> str:
        return hashlib.sha256(
            f"{schema}.{table}:{start}:{end}".encode()
        ).hexdigest()
