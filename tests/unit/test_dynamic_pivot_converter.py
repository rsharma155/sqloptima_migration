"""
Module: tests/unit/test_dynamic_pivot_converter.py
Purpose: TDD tests for item 3.6 — dynamic PIVOT conversion.
         Covers:
           - Regression: static PIVOT still works via StaticPivotRewriter
           - Dynamic PIVOT produces a DO $$ ... EXECUTE ... $$ block
           - That block contains STRING_AGG for building the column list dynamically
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import pytest

from domains.transpilation.converters.dynamic_pivot_converter import DynamicPivotConverter
from domains.transpilation.converters.pivot_converter import StaticPivotRewriter


# ---------------------------------------------------------------------------
# 3.6a — Static PIVOT regression (must still work)
# ---------------------------------------------------------------------------

class TestStaticPivotRegression:
    """Regression: static PIVOT conversion via StaticPivotRewriter must still work."""

    def test_static_pivot_basic(self):
        sql = (
            "SELECT region, [North], [South], [East], [West] "
            "FROM ("
            "  SELECT region, territory, sales FROM territories"
            ") AS src "
            "PIVOT ("
            "  SUM(sales) FOR territory IN ([North], [South], [East], [West])"
            ") AS pvt"
        )
        result = StaticPivotRewriter.rewrite(sql)
        assert result is not None, "StaticPivotRewriter.rewrite() should not return None for a valid PIVOT"
        assert "CASE WHEN" in result.upper(), "Static PIVOT must produce CASE WHEN conditional aggregation"
        assert "PIVOT" not in result.upper(), "Output must not contain PIVOT keyword"

    def test_static_pivot_produces_sum_cases(self):
        sql = (
            "SELECT category, [2023], [2024] "
            "FROM (SELECT category, yr, revenue FROM sales) AS s "
            "PIVOT (SUM(revenue) FOR yr IN ([2023], [2024])) AS p"
        )
        result = StaticPivotRewriter.rewrite(sql)
        assert result is not None
        assert "SUM(CASE WHEN" in result.upper()
        # Both pivot values should appear
        assert "2023" in result
        assert "2024" in result

    def test_non_pivot_sql_returns_none(self):
        sql = "SELECT id, name FROM users WHERE active = 1"
        result = StaticPivotRewriter.rewrite(sql)
        assert result is None, "Non-PIVOT SQL should return None"


# ---------------------------------------------------------------------------
# 3.6b — Dynamic PIVOT: DynamicPivotConverter
# ---------------------------------------------------------------------------

class TestDynamicPivotConverter:
    """Dynamic PIVOT must produce a DO $$ EXECUTE $$ block with STRING_AGG."""

    def test_returns_do_block(self):
        converter = DynamicPivotConverter()
        result = converter.convert(
            agg_func="SUM",
            pivot_col="category",
            value_col="amount",
            source_table="sales",
            group_col="region",
        )
        assert "DO $$" in result or "DO $" in result, (
            f"Dynamic PIVOT output must start with DO $$ block, got: {result[:100]!r}"
        )

    def test_contains_execute(self):
        converter = DynamicPivotConverter()
        result = converter.convert(
            agg_func="SUM",
            pivot_col="category",
            value_col="amount",
            source_table="sales",
            group_col="region",
        )
        assert "EXECUTE" in result.upper(), (
            f"Dynamic PIVOT output must contain EXECUTE, got: {result[:200]!r}"
        )

    def test_contains_string_agg(self):
        converter = DynamicPivotConverter()
        result = converter.convert(
            agg_func="SUM",
            pivot_col="category",
            value_col="amount",
            source_table="sales",
            group_col="region",
        )
        assert "STRING_AGG" in result.upper(), (
            f"Dynamic PIVOT output must contain STRING_AGG to build column list, got: {result[:300]!r}"
        )

    def test_contains_agg_function_name(self):
        """The output should include the agg function (SUM, AVG, etc.)."""
        converter = DynamicPivotConverter()
        result = converter.convert(
            agg_func="AVG",
            pivot_col="product",
            value_col="price",
            source_table="inventory",
            group_col="warehouse",
        )
        assert "AVG" in result.upper(), (
            f"Dynamic PIVOT output must include the aggregation function AVG: {result!r}"
        )

    def test_contains_source_table(self):
        converter = DynamicPivotConverter()
        result = converter.convert(
            agg_func="SUM",
            pivot_col="quarter",
            value_col="revenue",
            source_table="financials",
            group_col="department",
        )
        assert "financials" in result, (
            f"Source table 'financials' must appear in dynamic PIVOT output: {result!r}"
        )

    def test_contains_group_col(self):
        converter = DynamicPivotConverter()
        result = converter.convert(
            agg_func="MAX",
            pivot_col="status",
            value_col="count",
            source_table="orders",
            group_col="customer_id",
        )
        assert "customer_id" in result, (
            f"Group column 'customer_id' must appear in dynamic PIVOT output: {result!r}"
        )

    def test_do_block_ends_properly(self):
        """Block must close with END $$ or END; for valid PL/pgSQL."""
        converter = DynamicPivotConverter()
        result = converter.convert(
            agg_func="SUM",
            pivot_col="category",
            value_col="amount",
            source_table="sales",
            group_col="region",
        )
        assert "END" in result.upper(), (
            f"Dynamic PIVOT DO block must have an END clause: {result!r}"
        )

    def test_distinct_pivot_col_subquery(self):
        """The STRING_AGG must select distinct values of the pivot column."""
        converter = DynamicPivotConverter()
        result = converter.convert(
            agg_func="SUM",
            pivot_col="month",
            value_col="sales",
            source_table="monthly_sales",
            group_col="region",
        )
        # Should have DISTINCT or a subquery selecting distinct pivot values
        assert "DISTINCT" in result.upper() or "SELECT DISTINCT" in result.upper(), (
            f"Dynamic PIVOT must use DISTINCT on pivot column: {result!r}"
        )
