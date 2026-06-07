"""
Module: test_chunk_index_check.py
Purpose: TDD tests for item 9.2 — AssessmentEngine._check_chunking_column_indexed must
         warn when the chunking column has no index on the source table.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from domains.assessment.assessment_engine import AssessmentEngine


class TestCheckChunkingColumnIndexed:
    """Item 9.2: _check_chunking_column_indexed returns True/False based on sys.indexes."""

    def _make_source(self, rows: list) -> AsyncMock:
        source = AsyncMock()
        source.execute = AsyncMock(return_value=rows)
        return source

    @pytest.mark.asyncio
    async def test_returns_true_when_index_exists(self):
        """Should return True when sys.indexes query returns at least one row."""
        engine = AssessmentEngine()
        source = self._make_source([{"1": 1}])

        result = await engine._check_chunking_column_indexed(source, "dbo", "orders", "id")
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_no_index(self):
        """Should return False when sys.indexes query returns no rows."""
        engine = AssessmentEngine()
        source = self._make_source([])

        result = await engine._check_chunking_column_indexed(source, "dbo", "orders", "created_at")
        assert result is False

    @pytest.mark.asyncio
    async def test_query_uses_parameterized_placeholders(self):
        """The sys.indexes query must use positional placeholders, not f-string injection."""
        engine = AssessmentEngine()
        source = self._make_source([])

        await engine._check_chunking_column_indexed(source, "myschema", "mytable", "mycolumn")

        assert source.execute.call_count == 1
        call_args = source.execute.call_args

        # First positional argument must be the SQL string
        sql = call_args.args[0] if call_args.args else list(call_args.kwargs.values())[0]

        # SQL must contain sys.indexes join
        assert "sys.indexes" in sql

        # Must use positional ? placeholders (pyodbc style)
        assert "?" in sql, "Query must use ? placeholders for parameters"

        # Schema, table, column names must NOT appear literally in the SQL body
        assert "myschema" not in sql, "Schema name must be a parameter, not interpolated"
        assert "mytable" not in sql, "Table name must be a parameter, not interpolated"
        assert "mycolumn" not in sql, "Column name must be a parameter, not interpolated"

    @pytest.mark.asyncio
    async def test_correct_parameter_values_passed(self):
        """The schema, table, and column values must be forwarded as query parameters."""
        engine = AssessmentEngine()
        source = self._make_source([])

        await engine._check_chunking_column_indexed(source, "sales", "invoices", "invoice_date")

        call_args = source.execute.call_args
        # The remaining positional arguments (after query) should include schema/table/col
        all_args = list(call_args.args) + list(call_args.kwargs.values())
        flat = []
        for a in all_args:
            if isinstance(a, (list, tuple)):
                flat.extend(a)
            else:
                flat.append(a)

        assert "sales" in flat, f"Schema not passed as parameter; got {flat}"
        assert "invoices" in flat, f"Table not passed as parameter; got {flat}"
        assert "invoice_date" in flat, f"Column not passed as parameter; got {flat}"

    @pytest.mark.asyncio
    async def test_heap_excluded_index_type_zero(self):
        """The SQL must filter i.type > 0 to exclude heap (type=0)."""
        engine = AssessmentEngine()
        source = self._make_source([])

        await engine._check_chunking_column_indexed(source, "dbo", "t", "col")

        sql = source.execute.call_args.args[0]
        assert "i.type > 0" in sql or "type > 0" in sql, (
            "Query must exclude heaps (i.type > 0) but got: " + sql
        )


class TestAssessmentEngineChunkIndexWarning:
    """Integration: assess_table_with_source must add a warning when chunk col lacks index."""

    @pytest.mark.asyncio
    async def test_warn_when_chunk_column_not_indexed(self):
        """assess_table_with_source should add a WARNING when index check fails."""
        from shared.kernel.database_object import Table, Column, DataType

        engine = AssessmentEngine()
        source = AsyncMock()
        source.execute = AsyncMock(return_value=[])  # no index rows → not indexed

        col = Column(
            column_name="id",
            ordinal_position=1,
            data_type=DataType(type_name="int", max_length=4),
            is_nullable=False,
            is_identity=True,
        )
        table = Table(
            object_name="big_table",
            schema_name="dbo",
            database_name="testdb",
            columns=[col],
            row_count_estimate=100_000_000,
        )

        assessment = await engine.assess_table_with_source(
            table=table,
            source=source,
            chunk_col="id",
        )

        # Should have a warning about missing index
        warning_texts = " ".join(assessment.warnings).lower()
        assert "index" in warning_texts, (
            f"Expected an index-missing warning but got: {assessment.warnings}"
        )

    @pytest.mark.asyncio
    async def test_no_index_warning_when_column_is_indexed(self):
        """assess_table_with_source must NOT add an index warning when index exists."""
        from shared.kernel.database_object import Table, Column, DataType

        engine = AssessmentEngine()
        source = AsyncMock()
        source.execute = AsyncMock(return_value=[{"1": 1}])  # index found

        col = Column(
            column_name="id",
            ordinal_position=1,
            data_type=DataType(type_name="bigint", max_length=8),
            is_nullable=False,
            is_identity=True,
        )
        table = Table(
            object_name="users",
            schema_name="dbo",
            database_name="testdb",
            columns=[col],
            row_count_estimate=1_000,
        )

        assessment = await engine.assess_table_with_source(
            table=table,
            source=source,
            chunk_col="id",
        )

        warning_texts = " ".join(assessment.warnings).lower()
        assert "no index" not in warning_texts and "unindexed" not in warning_texts, (
            "Must not warn about missing index when index exists"
        )
