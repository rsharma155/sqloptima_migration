"""
Module: tests/unit/test_dateadd_converter.py
Purpose: Unit tests for DateAddConverter — DATEADD/DATEDIFF interval conversion.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import pytest

from domains.transpilation.converters.dateadd_converter import DateAddConverter


class TestDateAddConverter:
    """Test DATEADD/DATEDIFF pattern conversion to PL/pgSQL."""

    def test_dateadd_year(self) -> None:
        """Verify DATEADD(YEAR, 1, date) → date + INTERVAL '1 year'."""
        sql = "DATEADD(YEAR, 1, order_date)"
        converted, count = DateAddConverter.convert_dateadd(sql)
        assert count > 0
        assert 'INTERVAL' in converted
        assert 'year' in converted.lower()

    def test_dateadd_month(self) -> None:
        """Verify DATEADD(MONTH, -6, GETDATE()) converts correctly."""
        sql = "DATEADD(MONTH, -6, GETDATE())"
        converted, count = DateAddConverter.convert_dateadd(sql)
        assert count > 0
        assert 'INTERVAL' in converted
        assert '-' in converted or 'months' in converted.lower()

    def test_dateadd_day(self) -> None:
        """Verify DATEADD(DAY, 30, date) works."""
        sql = "DATEADD(DAY, 30, date_col)"
        converted, count = DateAddConverter.convert_dateadd(sql)
        assert count > 0
        assert 'INTERVAL' in converted

    def test_dateadd_hour(self) -> None:
        """Verify DATEADD(HOUR, 2, start_time) converts."""
        sql = "DATEADD(HOUR, 2, start_time)"
        converted, count = DateAddConverter.convert_dateadd(sql)
        assert count > 0
        assert 'INTERVAL' in converted
        assert 'hour' in converted.lower()

    def test_dateadd_minute(self) -> None:
        """Verify DATEADD(MINUTE, 15, time_col) works."""
        sql = "DATEADD(MINUTE, 15, time_col)"
        converted, count = DateAddConverter.convert_dateadd(sql)
        assert count > 0
        assert 'INTERVAL' in converted

    def test_dateadd_week(self) -> None:
        """Verify DATEADD(WEEK, 2, date) converts to 14 days or 2 weeks."""
        sql = "DATEADD(WEEK, 2, date_col)"
        converted, count = DateAddConverter.convert_dateadd(sql)
        assert count > 0
        assert 'INTERVAL' in converted

    def test_dateadd_negative_offset(self) -> None:
        """Verify negative offsets handled: DATEADD(MONTH, -3, date)."""
        sql = "DATEADD(MONTH, -3, hire_date)"
        converted, count = DateAddConverter.convert_dateadd(sql)
        assert count > 0
        assert 'INTERVAL' in converted
        # Either has minus or negative number
        assert '-' in converted or '(-' in converted

    def test_datediff_days(self) -> None:
        """Verify DATEDIFF(DAY, start, end) conversion."""
        sql = "DATEDIFF(DAY, start_date, end_date)"
        converted, count = DateAddConverter.convert_datediff(sql)
        assert count > 0
        # Should use date subtraction or EXTRACT
        assert 'EXTRACT' in converted or '-' in converted

    def test_datediff_month(self) -> None:
        """Verify DATEDIFF(MONTH, d1, d2) conversion."""
        sql = "DATEDIFF(MONTH, created_date, modified_date)"
        converted, count = DateAddConverter.convert_datediff(sql)
        assert count > 0

    def test_no_dateadd_no_changes(self) -> None:
        """Verify no changes when no DATEADD/DATEDIFF."""
        sql = "SELECT * FROM Orders WHERE order_date > '2020-01-01'"
        result = DateAddConverter.apply_all(sql)
        assert result.fixes_applied == 0
        assert result.sql == sql

    def test_multiple_dateadd_in_statement(self) -> None:
        """Verify multiple DATEADD calls in one statement."""
        sql = """
WHERE created >= DATEADD(MONTH, -12, GETDATE())
  AND due_date < DATEADD(WEEK, 2, GETDATE())
"""
        result = DateAddConverter.apply_all(sql)
        assert result.fixes_applied >= 2

    def test_dateadd_with_variables(self) -> None:
        """Verify DATEADD with variable offsets."""
        sql = "DATEADD(DAY, @num_days, @base_date)"
        result = DateAddConverter.apply_all(sql)
        assert result.fixes_applied > 0
        assert 'INTERVAL' in result.sql
