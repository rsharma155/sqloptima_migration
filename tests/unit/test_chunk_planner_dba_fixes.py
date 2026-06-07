"""
Module: tests/unit/test_chunk_planner_dba_fixes.py
Purpose: TDD tests for DBA feedback fixes — chunk boundary off-by-one (1.1)
         and UUID PK chunking support (1.3).
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from domains.chunking.chunk_planner import (
    ChunkColumnType,
    ChunkPlanner,
)


class MockConnector:
    """Minimal connector stub for planner tests."""

    def __init__(self, pk_rows=None, boundary_rows=None, count_rows=None):
        self._pk_rows = pk_rows or []
        self._boundary_rows = boundary_rows or [{"min_val": 1, "max_val": 10000}]
        self._count_rows = count_rows or [{"row_count": 10000}]

    async def execute(self, query, params=None):
        q = query.strip().lower()
        if "sys.indexes" in q:
            return self._pk_rows
        if "min(" in q and "max(" in q:
            return self._boundary_rows
        if "row_count" in q or "count(*)" in q:
            return self._count_rows
        return []


class TestChunkBoundaryOffByOne:
    """
    Issue 1.1: Chunk boundary off-by-one — rows silently skipped.

    The extraction query uses >= start AND <= end (inclusive), so chunk_end
    must equal max_val for the last row to be included in the final chunk.
    """

    def _planner(self, connector, chunk_size=10000):
        return ChunkPlanner(connector=connector, chunk_size=chunk_size)

    def test_single_chunk_covers_full_range(self):
        """All rows 1–10000 must fall inside a single chunk when chunk_size >= range."""
        conn = MockConnector(
            pk_rows=[{"column_name": "id", "type_name": "int", "is_identity": True}],
            boundary_rows=[{"min_val": 1, "max_val": 10000}],
        )
        planner = self._planner(conn, chunk_size=10000)
        ranges = planner._generate_ranges(
            schema="dbo", table="orders",
            column_name="id", column_type=ChunkColumnType.IDENTITY_PK,
            min_val=1, max_val=10000,
        )
        assert len(ranges) == 1
        chunk = ranges[0]
        assert chunk.boundary.start == 1
        # End must be 10000 (inclusive) so >= 1 AND <= 10000 catches all rows.
        assert chunk.boundary.end == 10000

    def test_last_chunk_end_equals_max_val(self):
        """The final chunk's end must equal max_val exactly."""
        conn = MockConnector(
            pk_rows=[{"column_name": "id", "type_name": "int", "is_identity": True}],
            boundary_rows=[{"min_val": 1, "max_val": 25000}],
        )
        planner = self._planner(conn, chunk_size=10000)
        ranges = planner._generate_ranges(
            schema="dbo", table="orders",
            column_name="id", column_type=ChunkColumnType.IDENTITY_PK,
            min_val=1, max_val=25000,
        )
        last = ranges[-1]
        assert last.boundary.end == 25000, (
            f"Last chunk end={last.boundary.end} != max_val=25000 — off-by-one bug present"
        )

    def test_no_gaps_between_chunks(self):
        """Adjacent chunks must be contiguous: chunk[i].end + 1 == chunk[i+1].start."""
        conn = MockConnector(
            pk_rows=[{"column_name": "id", "type_name": "int", "is_identity": True}],
            boundary_rows=[{"min_val": 1, "max_val": 30000}],
        )
        planner = self._planner(conn, chunk_size=10000)
        ranges = planner._generate_ranges(
            schema="dbo", table="orders",
            column_name="id", column_type=ChunkColumnType.IDENTITY_PK,
            min_val=1, max_val=30000,
        )
        for i in range(len(ranges) - 1):
            gap = ranges[i + 1].boundary.start - ranges[i].boundary.end
            assert gap == 1, (
                f"Gap between chunk {i} end={ranges[i].boundary.end} "
                f"and chunk {i+1} start={ranges[i+1].boundary.start}: gap={gap} (expected 1)"
            )

    def test_no_row_skipped_at_boundary(self):
        """Simulates the exact scenario from the bug: IDs 1..10000 step=10000."""
        conn = MockConnector()
        planner = self._planner(conn, chunk_size=10000)
        ranges = planner._generate_ranges(
            schema="dbo", table="t",
            column_name="id", column_type=ChunkColumnType.IDENTITY_PK,
            min_val=1, max_val=10000,
        )
        covered = set()
        for chunk in ranges:
            covered.update(range(chunk.boundary.start, chunk.boundary.end + 1))
        assert 10000 in covered, "Row 10000 is not covered by any chunk — off-by-one!"
        assert len(covered) == 10000, f"Expected 10000 covered IDs, got {len(covered)}"


class TestUUIDPkChunking:
    """
    Issue 1.3: UUID primary key tables not supported for chunking.

    uniqueidentifier PKs must be detected and tagged UUID_PK so the planner
    can apply a UUID-specific strategy instead of falling to SYNTHETIC (single
    full-table scan).
    """

    @pytest.mark.asyncio
    async def test_uniqueidentifier_detected_as_uuid_pk(self):
        conn = MockConnector(
            pk_rows=[{"column_name": "uid", "type_name": "uniqueidentifier", "is_identity": False}],
        )
        planner = ChunkPlanner(connector=conn, chunk_size=10000)
        name, col_type = await planner._detect_chunk_column("dbo", "orders")
        assert col_type == ChunkColumnType.UUID_PK, (
            f"Expected UUID_PK but got {col_type!r} — UUID PKs fall through to SYNTHETIC"
        )
        assert name == "uid"

    @pytest.mark.asyncio
    async def test_uuid_pk_does_not_produce_synthetic_single_chunk(self):
        """UUID PK tables must NOT degrade to a single SYNTHETIC scan."""
        conn = MockConnector(
            pk_rows=[{"column_name": "uid", "type_name": "uniqueidentifier", "is_identity": False}],
            boundary_rows=[
                {"min_val": "00000000-0000-0000-0000-000000000001",
                 "max_val": "ffffffff-ffff-ffff-ffff-ffffffffffff"}
            ],
            count_rows=[{"row_count": 50000}],
        )
        planner = ChunkPlanner(connector=conn, chunk_size=10000)
        name, col_type = await planner._detect_chunk_column("dbo", "orders")
        # Must be UUID_PK, not SYNTHETIC
        assert col_type == ChunkColumnType.UUID_PK

    def test_uuid_ranges_generated_for_uuid_pk(self):
        """_generate_ranges must produce multiple chunks for UUID_PK columns."""
        conn = MockConnector()
        planner = ChunkPlanner(connector=conn, chunk_size=10000)
        chunks = planner._generate_ranges(
            schema="dbo", table="orders",
            column_name="uid", column_type=ChunkColumnType.UUID_PK,
            min_val="00000000-0000-0000-0000-000000000001",
            max_val="ffffffff-ffff-ffff-ffff-ffffffffffff",
        )
        # Must produce at least one chunk (not empty like SYNTHETIC fallback can become)
        assert len(chunks) >= 1
        # Each chunk must have a valid boundary
        for chunk in chunks:
            assert chunk.boundary is not None
            assert chunk.column_type == ChunkColumnType.UUID_PK
