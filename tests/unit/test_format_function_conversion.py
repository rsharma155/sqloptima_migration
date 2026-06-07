"""
Module: tests/unit/test_format_function_conversion.py
Purpose: TDD tests for item 3.8 — FORMAT() function conversion.
         T-SQL FORMAT(value, format_string[, culture]) →
         PostgreSQL TO_CHAR(value, pg_format_string).
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import pytest

from domains.transpilation.converters.plpgsql._body_transforms import TsqlBodyConverter
from domains.transpilation.converters.plpgsql._format_converter import _convert_format_function


def _convert(sql: str) -> str:
    return TsqlBodyConverter.convert(sql, params=[])


class TestFormatFunctionDirect:
    """Unit tests for the _convert_format_function helper directly."""

    def test_yyyy_mm_dd_maps_to_pg(self):
        sql = "SELECT FORMAT(orderdate, 'yyyy-MM-dd')"
        result = _convert_format_function(sql)
        assert "TO_CHAR" in result.upper(), f"Expected TO_CHAR, got: {result!r}"
        assert "YYYY-MM-DD" in result.upper(), f"Expected YYYY-MM-DD format, got: {result!r}"

    def test_hh_mm_ss_maps_to_pg(self):
        sql = "SELECT FORMAT(ts, 'HH:mm:ss')"
        result = _convert_format_function(sql)
        assert "TO_CHAR" in result.upper()
        assert "HH24:MI:SS" in result.upper(), f"Expected HH24:MI:SS, got: {result!r}"

    def test_n2_numeric_format(self):
        sql = "SELECT FORMAT(amount, 'N2')"
        result = _convert_format_function(sql)
        assert "TO_CHAR" in result.upper()
        # N2 maps to a numeric format with 2 decimal places
        assert ".00" in result or "990.00" in result, f"Expected decimal format, got: {result!r}"

    def test_culture_arg_dropped(self):
        """FORMAT with 3 args (value, fmt, culture) — culture should be dropped."""
        sql = "SELECT FORMAT(GETDATE(), 'yyyy-MM-dd', 'en-US')"
        result = _convert_format_function(sql)
        # Culture arg should be stripped; result should be TO_CHAR with 2 args
        assert "en-US" not in result, f"Culture arg should be dropped, got: {result!r}"
        assert "TO_CHAR" in result.upper()

    def test_unknown_format_passes_through(self):
        """Unknown format strings should be passed through unchanged (not crashed)."""
        sql = "SELECT FORMAT(val, 'custom-format')"
        result = _convert_format_function(sql)
        assert "TO_CHAR" in result.upper(), f"Should still produce TO_CHAR: {result!r}"

    def test_date_slash_format(self):
        sql = "SELECT FORMAT(d, 'dd/MM/yyyy')"
        result = _convert_format_function(sql)
        assert "TO_CHAR" in result.upper()
        assert "DD/MM/YYYY" in result.upper()

    def test_datetime_combined_format(self):
        sql = "SELECT FORMAT(ts, 'yyyy-MM-dd HH:mm:ss')"
        result = _convert_format_function(sql)
        assert "TO_CHAR" in result.upper()
        assert "YYYY-MM-DD" in result.upper()
        assert "HH24:MI:SS" in result.upper()


class TestFormatFunctionViaConverter:
    """Integration: FORMAT() must be converted through the full TsqlBodyConverter pipeline."""

    def test_format_getdate_converted(self):
        sql = "SELECT FORMAT(GETDATE(), 'yyyy-MM-dd')"
        result = _convert(sql)
        # FORMAT should be converted away
        assert "FORMAT(" not in result or "TO_CHAR" in result.upper(), (
            f"FORMAT() must be replaced with TO_CHAR: {result!r}"
        )

    def test_format_date_column(self):
        sql = "SET @ds = FORMAT(order_date, 'yyyy-MM-dd')"
        result = _convert(sql)
        assert "FORMAT(" not in result or "TO_CHAR" in result.upper()

    def test_format_number_n0(self):
        sql = "SELECT FORMAT(total, 'N0') FROM orders"
        result = _convert(sql)
        assert "FORMAT(" not in result or "TO_CHAR" in result.upper()

    def test_format_with_culture_three_args(self):
        sql = "SELECT FORMAT(sale_date, 'MM/dd/yyyy', 'en-US') FROM sales"
        result = _convert(sql)
        assert "FORMAT(" not in result or "TO_CHAR" in result.upper()
        assert "en-US" not in result, "Culture arg must be dropped"
