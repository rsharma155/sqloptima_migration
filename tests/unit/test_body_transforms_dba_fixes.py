"""
Module: tests/unit/test_body_transforms_dba_fixes.py
Purpose: TDD tests for DBA feedback fixes in _body_transforms.py:
         3.1 — CHARINDEX → STRPOS argument order inverted.
         3.2 — STR() → TO_CHAR() semantically wrong.
         3.3 — DATEDIFF wrong for sub-day units (SECOND/MINUTE/HOUR).
         3.4 — SELECT INTO not converted to CREATE TABLE AS.
         3.5 — @@TRANCOUNT silently mapped to 0 (needs TODO comment).
         3.10 — ERROR_SEVERITY/ERROR_STATE silently zeroed (needs TODO comment).
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import pytest

from domains.transpilation.converters.plpgsql._body_transforms import TsqlBodyConverter


def _convert(sql: str) -> str:
    """Run the full converter pipeline with no params."""
    return TsqlBodyConverter.convert(sql, params=[])


class TestCharindexArgumentOrder:
    """
    Issue 3.1: CHARINDEX(substring, string) must become STRPOS(string, substring).
    The current code just renames the function without swapping args, producing
    semantically wrong SQL.
    """

    def test_charindex_args_swapped(self):
        sql = "SELECT CHARINDEX('x', col) FROM t"
        result = _convert(sql)
        # STRPOS must have the arguments in (string, substring) order
        assert "STRPOS(col, 'x')" in result, (
            f"CHARINDEX args not swapped: got {result!r}"
        )
        assert "STRPOS('x', col)" not in result, (
            "Old wrong argument order still present"
        )

    def test_charindex_with_start_position_uses_position(self):
        """CHARINDEX with 3-arg form (substring, string, start) must be handled."""
        sql = "SELECT CHARINDEX('x', col, 3) FROM t"
        result = _convert(sql)
        # Must produce a STRPOS call or a POSITION-based form; must NOT keep wrong order
        assert "STRPOS('x', col" not in result, (
            f"Wrong argument order with 3-arg CHARINDEX: {result!r}"
        )

    def test_charindex_case_insensitive(self):
        sql = "SELECT CHARINDEX('abc', myCol) FROM t"
        result = _convert(sql)
        assert "STRPOS(myCol, 'abc')" in result


class TestStrFunctionConversion:
    """
    Issue 3.2: STR(expr) must NOT produce TO_CHAR(expr) without a format string.
    STR(123.456, 6, 2) must produce TO_CHAR with a proper format mask.
    """

    def test_str_single_arg_casts_to_text(self):
        sql = "SELECT STR(123)"
        result = _convert(sql)
        # Single-arg STR must produce CAST(... AS TEXT) not TO_CHAR with missing args
        assert "CAST(123 AS TEXT)" in result or "::TEXT" in result or "::text" in result, (
            f"STR(single-arg) must cast to text, got: {result!r}"
        )
        # Must NOT produce bare TO_CHAR(123) with no format — invalid PG syntax
        assert "TO_CHAR(123)" not in result, (
            f"TO_CHAR without format string is invalid PG syntax: {result!r}"
        )

    def test_str_with_width_and_decimals(self):
        sql = "SELECT STR(123.456, 6, 2)"
        result = _convert(sql)
        # Must produce TO_CHAR with a format mask, not TO_CHAR(123.456, 6, 2)
        assert "TO_CHAR(123.456, 6, 2)" not in result, (
            "TO_CHAR does not accept (expr, width, decimals) — fix 3.2 not applied"
        )
        assert "TO_CHAR" in result or "CAST" in result


class TestDatediffSubDayUnits:
    """
    Issue 3.3: DATEDIFF for SECOND/MINUTE/HOUR must use EPOCH-based arithmetic.
    EXTRACT(SECOND FROM interval) returns the seconds component (0–59), not total seconds.
    """

    def test_datediff_second_uses_epoch(self):
        sql = "SELECT DATEDIFF(SECOND, start_dt, end_dt)"
        result = _convert(sql)
        # Must use EPOCH extraction, not EXTRACT(SECOND FROM ...)
        assert "EPOCH" in result.upper(), (
            f"DATEDIFF(SECOND) must use EPOCH — got: {result!r}"
        )
        # Must NOT use EXTRACT(SECOND FROM ...) which returns 0-59 component
        import re
        # Check for the broken pattern: EXTRACT(SECOND FROM (end - start))
        bad = re.search(r"EXTRACT\s*\(\s*SECOND\s+FROM\s+\([^)]+\)\s*\)", result, re.IGNORECASE)
        assert bad is None, (
            f"DATEDIFF(SECOND) produces wrong EXTRACT pattern: {result!r}"
        )

    def test_datediff_minute_uses_epoch(self):
        sql = "SELECT DATEDIFF(MINUTE, t1, t2)"
        result = _convert(sql)
        assert "EPOCH" in result.upper(), (
            f"DATEDIFF(MINUTE) must use EPOCH: {result!r}"
        )
        assert "/ 60" in result, f"DATEDIFF(MINUTE) must divide by 60: {result!r}"

    def test_datediff_hour_uses_epoch(self):
        sql = "SELECT DATEDIFF(HOUR, t1, t2)"
        result = _convert(sql)
        assert "EPOCH" in result.upper()
        assert "/ 3600" in result or "3600" in result

    def test_datediff_day_still_works(self):
        """Regression: DAY-level DATEDIFF must still produce a valid result."""
        sql = "SELECT DATEDIFF(DAY, start_date, end_date)"
        result = _convert(sql)
        assert "EXTRACT" in result.upper() or "EPOCH" in result.upper()

    def test_datediff_year_still_works(self):
        sql = "SELECT DATEDIFF(YEAR, d1, d2)"
        result = _convert(sql)
        assert result  # must produce something, not crash


class TestSelectIntoConversion:
    """
    Issue 3.4: SELECT ... INTO #tmp FROM ... must be converted to
    CREATE TEMP TABLE tmp AS SELECT ... FROM ...
    """

    def test_select_into_temp_table(self):
        sql = "SELECT OrderID, CustomerID INTO #Orders_2024 FROM dbo.Orders"
        result = _convert(sql)
        assert "CREATE" in result.upper() and "TABLE" in result.upper(), (
            f"SELECT INTO must produce CREATE TABLE: {result!r}"
        )
        # Temp table hash prefix must be stripped
        assert "#Orders_2024" not in result, (
            "# prefix must be stripped from temp table name"
        )

    def test_select_into_permanent_table(self):
        sql = "SELECT id, name INTO new_table FROM old_table"
        result = _convert(sql)
        assert "CREATE" in result.upper() and "TABLE" in result.upper()


class TestTranscountMapping:
    """
    Issue 3.5: @@TRANCOUNT must emit a TODO comment, not silently map to 0.
    """

    def test_trancount_includes_todo_comment(self):
        sql = "IF @@TRANCOUNT > 0 ROLLBACK"
        result = _convert(sql)
        # Must include a TODO comment — silent 0 hides logic
        assert "TODO" in result.upper() or "trancount" in result.lower(), (
            f"@@TRANCOUNT must include a TODO comment: {result!r}"
        )


class TestErrorFunctionsTodoComments:
    """
    Issue 3.10: ERROR_SEVERITY() / ERROR_STATE() must include TODO comments
    so developers know to review these.
    """

    def test_error_severity_includes_todo(self):
        sql = "SET @sev = ERROR_SEVERITY()"
        result = _convert(sql)
        assert "TODO" in result.upper(), (
            f"ERROR_SEVERITY() must include a TODO comment: {result!r}"
        )

    def test_error_state_includes_todo(self):
        sql = "SET @state = ERROR_STATE()"
        result = _convert(sql)
        assert "TODO" in result.upper(), (
            f"ERROR_STATE() must include a TODO comment: {result!r}"
        )
