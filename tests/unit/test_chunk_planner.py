"""
Module: test_chunk_planner.py
Purpose: Unit tests
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from domains.chunking.chunk_planner import (
    ChunkBoundary,
    ChunkColumnType,
    ChunkPlan,
    ChunkPlanner,
    ChunkStatus,
)


class TestChunkBoundary:
    def test_create_boundary(self):
        b = ChunkBoundary(start=1, end=100)
        assert b.start == 1
        assert b.end == 100

    def test_hash_consistency(self):
        b1 = ChunkBoundary(start=1, end=100)
        b2 = ChunkBoundary(start=1, end=100)
        assert b1.hash == b2.hash

    def test_hash_different(self):
        b1 = ChunkBoundary(start=1, end=100)
        b2 = ChunkBoundary(start=1, end=200)
        assert b1.hash != b2.hash


class TestChunkPlan:
    def test_create_plan(self):
        plan = ChunkPlan(
            table_schema="dbo",
            table_name="orders",
            boundary=ChunkBoundary(start=1, end=10000),
            column_name="id",
            column_type=ChunkColumnType.IDENTITY_PK,
        )
        assert plan.qualified_name == "dbo.orders"
        assert plan.status == ChunkStatus.PENDING
        assert plan.chunk_hash != ""

    def test_hash_uniqueness(self):
        plan1 = ChunkPlan(
            table_schema="dbo",
            table_name="orders",
            boundary=ChunkBoundary(start=1, end=10000),
            column_name="id",
        )
        plan2 = ChunkPlan(
            table_schema="dbo",
            table_name="orders",
            boundary=ChunkBoundary(start=10001, end=20000),
            column_name="id",
        )
        assert plan1.chunk_hash != plan2.chunk_hash

    def test_hash_different_table(self):
        plan1 = ChunkPlan(
            table_schema="dbo",
            table_name="orders",
            boundary=ChunkBoundary(start=1, end=10000),
            column_name="id",
        )
        plan2 = ChunkPlan(
            table_schema="dbo",
            table_name="customers",
            boundary=ChunkBoundary(start=1, end=10000),
            column_name="id",
        )
        assert plan1.chunk_hash != plan2.chunk_hash


class TestChunkPlanner:
    @pytest.fixture
    def mock_connector(self):
        conn = AsyncMock()
        return conn

    @pytest.mark.asyncio
    async def test_detect_identity_pk(self, mock_connector):
        mock_connector.execute.return_value = [
            {"column_name": "id", "type_name": "bigint", "is_identity": True},
        ]
        planner = ChunkPlanner(mock_connector)
        col, col_type = await planner._detect_chunk_column("dbo", "orders")
        assert col == "id"
        assert col_type == ChunkColumnType.IDENTITY_PK

    @pytest.mark.asyncio
    async def test_detect_bigint_pk(self, mock_connector):
        mock_connector.execute.return_value = [
            {"column_name": "order_id", "type_name": "bigint", "is_identity": False},
        ]
        planner = ChunkPlanner(mock_connector)
        col, col_type = await planner._detect_chunk_column("dbo", "orders")
        assert col == "order_id"
        assert col_type == ChunkColumnType.BIGINT_PK

    @pytest.mark.asyncio
    async def test_detect_fallback_to_synthetic(self, mock_connector):
        mock_connector.execute.side_effect = Exception("No PK")
        planner = ChunkPlanner(mock_connector)
        col, col_type = await planner._detect_chunk_column("dbo", "orders")
        assert col_type == ChunkColumnType.SYNTHETIC

    @pytest.mark.asyncio
    async def test_get_boundaries(self, mock_connector):
        mock_connector.execute.return_value = [
            {"min_val": 1, "max_val": 100000},
        ]
        planner = ChunkPlanner(mock_connector)
        min_val, max_val = await planner._get_boundaries("dbo", "orders", "id")
        assert min_val == 1
        assert max_val == 100000

    @pytest.mark.asyncio
    async def test_get_boundaries_empty_table(self, mock_connector):
        mock_connector.execute.return_value = []
        planner = ChunkPlanner(mock_connector)
        min_val, max_val = await planner._get_boundaries("dbo", "empty", "id")
        assert min_val is None
        assert max_val is None

    @pytest.mark.asyncio
    async def test_plan_table_generates_chunks(self, mock_connector):
        async def execute_side_effect(query, params=None):
            if "MIN" in query and "MAX" in query:
                return [{"min_val": 1, "max_val": 50000}]
            if "sys.partitions" in query:
                return [{"row_count": 50000}]
            if "is_primary_key" in query or "sys.indexes" in query:
                return [{"column_name": "id", "type_name": "bigint", "is_identity": True}]
            if "COUNT(*)" in query:
                return [{"cnt": 50000}]
            return []

        mock_connector.execute = execute_side_effect
        planner = ChunkPlanner(mock_connector, chunk_size=10000)
        result = await planner.plan_table("dbo", "orders")
        assert len(result.chunks) == 5
        assert result.total_rows_estimate == 50000
        assert result.column_name == "id"
        assert result.min_value == 1
        assert result.max_value == 50000

    @pytest.mark.asyncio
    async def test_plan_table_single_chunk(self, mock_connector):
        async def execute_side_effect(query, params=None):
            if "MIN" in query and "MAX" in query:
                return [{"min_val": 1, "max_val": 5000}]
            if "sys.partitions" in query:
                return [{"row_count": 5000}]
            if "is_primary_key" in query or "sys.indexes" in query:
                return [{"column_name": "id", "type_name": "int", "is_identity": True}]
            return []

        mock_connector.execute = execute_side_effect
        planner = ChunkPlanner(mock_connector, chunk_size=10000)
        result = await planner.plan_table("dbo", "small_table")
        assert len(result.chunks) == 1
        assert result.chunks[0].boundary.start == 1
        assert result.chunks[0].boundary.end == 5000

    def test_generate_ranges(self):
        planner = ChunkPlanner(MagicMock(), chunk_size=10000)
        chunks = planner._generate_ranges(
            schema="dbo",
            table="orders",
            column_name="id",
            column_type=ChunkColumnType.IDENTITY_PK,
            min_val=1,
            max_val=50000,
        )
        assert len(chunks) == 5
        assert chunks[0].boundary.start == 1
        assert chunks[0].boundary.end == 10000
        assert chunks[4].boundary.start == 40001
        assert chunks[4].boundary.end == 50000

    def test_generate_ranges_exact_multiple(self):
        planner = ChunkPlanner(MagicMock(), chunk_size=10000)
        chunks = planner._generate_ranges(
            schema="dbo",
            table="orders",
            column_name="id",
            column_type=ChunkColumnType.IDENTITY_PK,
            min_val=1,
            max_val=30000,
        )
        assert len(chunks) == 3

    def test_compute_chunk_hash(self):
        planner = ChunkPlanner(MagicMock())
        h1 = planner.compute_chunk_hash("dbo", "orders", 1, 10000)
        h2 = planner.compute_chunk_hash("dbo", "orders", 1, 10000)
        h3 = planner.compute_chunk_hash("dbo", "orders", 10001, 20000)
        assert h1 == h2
        assert h1 != h3

    @pytest.mark.asyncio
    async def test_get_approximate_count_uses_sys_partitions(self, mock_connector):
        mock_connector.execute.return_value = [{"row_count": 50000}]
        planner = ChunkPlanner(mock_connector)
        count = await planner._get_approximate_count("dbo", "orders")
        assert count == 50000

    @pytest.mark.asyncio
    async def test_split_skewed_chunk(self, mock_connector):
        mock_connector.execute.return_value = [{"mid": 55000}]
        planner = ChunkPlanner(mock_connector)
        chunk = ChunkPlan(
            table_schema="dbo",
            table_name="orders",
            boundary=ChunkBoundary(start=1, end=100000),
            column_name="id",
        )
        split = await planner.split_skewed_chunk(chunk, "dbo", "orders")
        assert len(split) == 2
        assert split[0].boundary.end == 55000
        assert split[1].boundary.start == 55001

    @pytest.mark.asyncio
    async def test_plan_table_empty(self, mock_connector):
        mock_connector.execute.return_value = [{"min_val": None, "max_val": None}]
        planner = ChunkPlanner(mock_connector)
        result = await planner.plan_table("dbo", "empty")
        assert len(result.chunks) == 0
        assert result.total_rows_estimate == 0

    @pytest.mark.asyncio
    async def test_detect_rowversion_pk(self, mock_connector):
        mock_connector.execute.return_value = [
            {"column_name": "rowver", "type_name": "rowversion", "is_identity": False},
        ]
        planner = ChunkPlanner(mock_connector)
        col, col_type = await planner._detect_chunk_column("dbo", "t")
        assert col == "rowver"
        assert col_type == ChunkColumnType.ROWVERSION

    @pytest.mark.asyncio
    async def test_detect_timestamp_pk(self, mock_connector):
        mock_connector.execute.return_value = [
            {"column_name": "ts", "type_name": "timestamp", "is_identity": False},
        ]
        planner = ChunkPlanner(mock_connector)
        col, col_type = await planner._detect_chunk_column("dbo", "t")
        assert col == "ts"
        assert col_type == ChunkColumnType.ROWVERSION

    @pytest.mark.asyncio
    async def test_detect_smallint_pk(self, mock_connector):
        mock_connector.execute.return_value = [
            {"column_name": "id", "type_name": "smallint", "is_identity": False},
        ]
        planner = ChunkPlanner(mock_connector)
        col, col_type = await planner._detect_chunk_column("dbo", "t")
        assert col_type == ChunkColumnType.BIGINT_PK

    @pytest.mark.asyncio
    async def test_detect_rowversion_fallback(self, mock_connector):
        mock_connector.execute.side_effect = [
            Exception("No PK"),
            [{"column_name": "rowver", "type_name": "rowversion"}],
        ]
        planner = ChunkPlanner(mock_connector)
        col, col_type = await planner._detect_chunk_column("dbo", "t")
        assert col_type == ChunkColumnType.ROWVERSION

    @pytest.mark.asyncio
    async def test_detect_composite_columns(self, mock_connector):
        mock_connector.execute.return_value = [
            {"column_name": "tenant_id", "type_name": "int", "is_identity": False},
            {"column_name": "id", "type_name": "bigint", "is_identity": False},
        ]
        planner = ChunkPlanner(mock_connector)
        cols, ctype = await planner._detect_chunk_columns_composite("dbo", "orders")
        assert len(cols) == 2
        assert cols[0][0] == "tenant_id"
        assert cols[1][0] == "id"

    @pytest.mark.asyncio
    async def test_plan_table_with_composite(self, mock_connector):
        async def execute_side_effect(query, params=None):
            if "key_ordinal" in query or "sys.indexes" in query:
                return [
                    {"column_name": "tenant_id", "type_name": "int", "is_identity": False},
                    {"column_name": "id", "type_name": "bigint", "is_identity": False},
                ]
            if "MIN" in query and "MAX" in query:
                return [{"min_val": 1, "max_val": 50000}]
            if "sys.partitions" in query:
                return [{"row_count": 50000}]
            return []

        mock_connector.execute = execute_side_effect
        planner = ChunkPlanner(mock_connector, chunk_size=10000)
        result = await planner.plan_table("dbo", "orders", use_composite=True)
        assert len(result.chunks) > 0
        assert result.column_name == "tenant_id,id"

    def test_generate_ranges_composite(self):
        planner = ChunkPlanner(MagicMock(), chunk_size=10000)
        chunks = planner._generate_ranges_composite(
            schema="dbo",
            table="orders",
            column_names=["tenant_id", "id"],
            column_types=[ChunkColumnType.BIGINT_PK, ChunkColumnType.BIGINT_PK],
            min_val=1,
            max_val=50000,
        )
        assert len(chunks) == 5
        assert chunks[0].boundary.start == 1
        assert chunks[0].boundary.end == 10000

    @pytest.mark.asyncio
    async def test_split_skewed_chunk_auto_no_split(self, mock_connector):
        planner = ChunkPlanner(mock_connector)
        chunk = ChunkPlan(
            table_schema="dbo", table_name="orders",
            boundary=ChunkBoundary(start=1, end=1000),
            column_name="id",
        )
        result = await planner.split_skewed_chunk_auto(chunk, "dbo", "orders", 5000, timeout_ms=10000)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_split_skewed_chunk_auto_triggers_split(self, mock_connector):
        mock_connector.execute.return_value = [{"mid": 500}]
        planner = ChunkPlanner(mock_connector)
        chunk = ChunkPlan(
            table_schema="dbo", table_name="orders",
            boundary=ChunkBoundary(start=1, end=1000),
            column_name="id",
        )
        result = await planner.split_skewed_chunk_auto(chunk, "dbo", "orders", 15000, timeout_ms=10000)
        assert len(result) == 2
