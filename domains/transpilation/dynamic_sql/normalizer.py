"""
Module: normalizer.py
Purpose: Normalizes dynamic T-SQL patterns into static SQL suitable for
         PostgreSQL conversion. Handles IF predicates, dynamic ORDER BY,
         dynamic table names, and variable concatenation.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import re
from typing import Any

import sqlglot
from sqlglot import exp

from domains.transpilation.dynamic_sql.models import (
    ConditionalPredicate,
    ConversionWarning,
    Severity,
)
from domains.transpilation.dynamic_sql.symbol_table import SymbolTable

_VARIABLE_REF = re.compile(r"@\w+")
_DYNAMIC_TABLE_PATTERN = re.compile(
    r"(?:FROM|JOIN|UPDATE|INTO)\s+(?:@\w+)",
    re.IGNORECASE,
)
_DYNAMIC_ORDER_BY_PATTERN = re.compile(
    r"ORDER\s+BY\s+(?:@\w+)",
    re.IGNORECASE,
)
_DYNAMIC_COLUMN_PATTERN = re.compile(
    r"(?:WHERE|AND|OR|SET)\s+\w+\s*(?:=|LIKE|IN|>|<|>=|<=|!=)\s*\+\s*@\w+",
    re.IGNORECASE,
)


class SqlNormalizer:
    """Normalizes dynamic SQL patterns to static SQL equivalents."""

    def __init__(self, symbol_table: SymbolTable):
        self.symbol_table = symbol_table
        self.warnings: list[ConversionWarning] = []

    def normalize(self, sql: str) -> str:
        """Apply all normalizations to produce static SQL."""
        result = self._replace_variable_concat(sql)
        result = self._normalize_dynamic_predicates(result)
        result = self._normalize_dynamic_order_by(result)
        result = self._flag_dynamic_tables(result)
        result = self._clean_string_literals(result)
        return result

    def _replace_variable_concat(self, sql: str) -> str:
        """Replace CAST(@x AS VARCHAR) + @y patterns with direct variable refs."""
        result = sql

        cast_pattern = re.compile(
            r"CAST\s*\(\s*(@\w+)\s*AS\s+\w+(?:\([^)]*\))?\s*\)",
            re.IGNORECASE,
        )
        result = cast_pattern.sub(r"\1", result)

        string_add_pattern = re.compile(
            r"(\s*\+\s*N?'[^']*')|(N?'[^']*'\s*\+\s*)",
            re.IGNORECASE,
        )
        result = string_add_pattern.sub(" ", result)

        concat_pattern = re.compile(
            r"'([^']*)'\s*\+\s*(@\w+)\s*\+\s*'([^']*)'",
            re.IGNORECASE,
        )
        result = concat_pattern.sub(
            lambda m: f"'{m.group(1)}' || {m.group(2)} || '{m.group(3)}'",
            result,
        )

        simple_concat = re.compile(r"'([^']*)'\s*\+\s*(@\w+)", re.IGNORECASE)
        result = simple_concat.sub(
            lambda m: f"'{m.group(1)}' || {m.group(2)}", result
        )

        concat_right = re.compile(r"(@\w+)\s*\+\s*'([^']*)'", re.IGNORECASE)
        result = concat_right.sub(
            lambda m: f"{m.group(1)} || '{m.group(2)}'", result
        )

        return result

    def _normalize_dynamic_predicates(self, sql: str) -> str:
        """Transform conditional predicate concatenation into proper SQL patterns.

        E.g.:
          WHERE 1=1 AND CustomerId=' + @CustomerId + '
        becomes:
          WHERE (@CustomerId IS NULL OR CustomerId = @CustomerId)
        """
        result = sql

        pred_pattern = re.compile(
            r"AND\s+(\w+\.?\w*)\s*=\s*'?\s*'\s*\+\s*(@\w+)\s*\+\s*'",
            re.IGNORECASE,
        )
        result = pred_pattern.sub(
            r"AND (\2 IS NULL OR \1 = \2)", result
        )

        pred_pattern2 = re.compile(
            r"WHERE\s+1\s*=\s*1\s*(AND\s+.+)",
            re.IGNORECASE,
        )
        if re.search(r"WHERE\s+1\s*=\s*1", result, re.IGNORECASE):
            where_rest = re.split(
                r"WHERE\s+1\s*=\s*1", result, maxsplit=1, flags=re.IGNORECASE
            )
            if len(where_rest) > 1:
                rest = where_rest[1].strip()
                if rest:
                    result = where_rest[0] + "WHERE " + rest.lstrip("AND ")

        return result

    def _normalize_dynamic_order_by(self, sql: str) -> str:
        """Convert dynamic ORDER BY @SortColumn to CASE expression."""
        match = re.search(
            r"ORDER\s+BY\s+(?:@(\w+))(?:\s*(?:ASC|DESC))?",
            sql,
            re.IGNORECASE,
        )
        if match:
            var = "@" + match.group(1)
            self.warnings.append(
                ConversionWarning(
                    severity=Severity.HIGH,
                    code="DYNAMIC_ORDER_BY",
                    message=(
                        f"Dynamic ORDER BY using {var} detected. "
                        f"Convert to CASE expression or flag for manual review."
                    ),
                    original_sql=sql,
                )
            )
        return sql

    def _flag_dynamic_tables(self, sql: str) -> str:
        """Flag dynamic table references for manual review."""
        if _DYNAMIC_TABLE_PATTERN.search(sql):
            self.warnings.append(
                ConversionWarning(
                    severity=Severity.CRITICAL,
                    code="DYNAMIC_TABLE_REFERENCE",
                    message=(
                        "Dynamic table name detected. "
                        "Cannot safely convert — requires manual review."
                    ),
                    original_sql=sql,
                )
            )
        return sql

    def _clean_string_literals(self, sql: str) -> str:
        """Clean up N'...' literals and excess whitespace."""
        result = sql
        result = re.sub(r"\bN'", "'", result)
        result = re.sub(r"\s+", " ", result)
        return result.strip()

    def apply_conditional_predicates(
        self, predicates: list[ConditionalPredicate]
    ) -> str:
        """Generate WHERE clause from conditional predicates.

        Input: [ConditionalPredicate("@id", "IS NOT NULL", "AND id = @id")]
        Output: (@id IS NULL OR id = @id)
        """
        clauses: list[str] = []
        for p in predicates:
            if p.condition.upper() == "IS NOT NULL":
                clauses.append(
                    f"({p.variable} IS NULL OR {p.sql_fragment.lstrip('AND ').lstrip('OR ').strip()})"
                )
            elif p.condition.upper() == "IS NULL":
                clauses.append(
                    f"({p.variable} IS NOT NULL AND {p.sql_fragment.lstrip('AND ').lstrip('OR ').strip()})"
                )
            else:
                clauses.append(p.sql_fragment)
        return "\n".join(clauses)

    def get_warnings(self) -> list[ConversionWarning]:
        return self.warnings
