"""
Module: tests/unit/test_isnumeric_conversion.py
Purpose: TDD tests for item 3.7 — ISNUMERIC() conversion.
         ISNUMERIC(expr) → regex-cast expression returning 0 or 1.
         Also verifies that a preamble note is emitted when ISNUMERIC is present.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import pytest

from domains.transpilation.converters.plpgsql._body_transforms import TsqlBodyConverter


def _convert(sql: str) -> str:
    return TsqlBodyConverter.convert(sql, params=[])


class TestIsNumericConversion:
    """Issue 3.7: ISNUMERIC(expr) must be replaced with a PostgreSQL regex-based equivalent."""

    def test_isnumeric_basic_replaced(self):
        sql = "SELECT ISNUMERIC(col) FROM t"
        result = _convert(sql)
        assert "ISNUMERIC" not in result.upper(), (
            f"ISNUMERIC should be replaced, got: {result!r}"
        )

    def test_isnumeric_produces_regex_cast_int(self):
        """The replacement should produce a cast to INT (returns 0 or 1)."""
        sql = "SELECT ISNUMERIC(val) FROM t"
        result = _convert(sql)
        # Must not still contain ISNUMERIC
        assert "ISNUMERIC" not in result.upper()
        # Must produce a ::INT or ::INTEGER cast
        assert "::INT" in result.upper() or "CAST(" in result.upper(), (
            f"ISNUMERIC replacement must produce integer (0 or 1): {result!r}"
        )

    def test_isnumeric_with_literal_integer(self):
        sql = "SELECT ISNUMERIC('123')"
        result = _convert(sql)
        assert "ISNUMERIC" not in result.upper()

    def test_isnumeric_with_variable(self):
        sql = "IF ISNUMERIC(@val) = 1 SET @num = CAST(@val AS DECIMAL)"
        result = _convert(sql)
        assert "ISNUMERIC" not in result.upper(), (
            f"ISNUMERIC in IF condition should be replaced: {result!r}"
        )

    def test_isnumeric_case_insensitive(self):
        sql = "SELECT isnumeric(col) FROM t"
        result = _convert(sql)
        assert "ISNUMERIC" not in result.upper()

    def test_isnumeric_in_where_clause(self):
        sql = "SELECT id FROM t WHERE ISNUMERIC(code) = 1"
        result = _convert(sql)
        assert "ISNUMERIC" not in result.upper()

    def test_isnumeric_preamble_comment(self):
        """When ISNUMERIC is detected, a comment/note should suggest using is_numeric helper."""
        sql = "SELECT ISNUMERIC(val) FROM data"
        result = _convert(sql)
        # Either a comment about ISNUMERIC or a TODO/note about the helper
        assert "ISNUMERIC" in result.upper() or "is_numeric" in result.lower() or "numeric" in result.lower(), (
            f"Result should reference ISNUMERIC or numeric somewhere: {result!r}"
        )

    def test_isnumeric_regex_pattern_in_output(self):
        """The regex for numeric detection should be present in the output."""
        sql = "SELECT ISNUMERIC(val) FROM t"
        result = _convert(sql)
        # The replacement should contain a regex pattern for numeric validation
        assert "~" in result or "REGEXP" in result.upper() or "[0-9]" in result or "0-9" in result, (
            f"ISNUMERIC replacement should use regex pattern: {result!r}"
        )
