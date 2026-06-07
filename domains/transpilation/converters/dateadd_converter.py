"""
Module: domains/transpilation/converters/dateadd_converter.py
Purpose: Converts T-SQL DATEADD/DATEDIFF to PL/pgSQL INTERVAL expressions.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass
class EnhancementResult:
    """Result of applying dateadd enhancements."""

    sql: str
    warnings: List[str] = field(default_factory=list)
    fixes_applied: int = 0


class DateAddConverter:
    """Handles T-SQL DATEADD/DATEDIFF to PostgreSQL INTERVAL conversion.

    DATEADD pattern: DATEADD(unit, offset, date) → (date +/- INTERVAL 'offset unit')
    DATEDIFF pattern: DATEDIFF(unit, d1, d2) → (d2 - d1)::unit or EXTRACT(unit FROM (d2 - d1))
    """

    # Map SQL Server date unit abbreviations to PostgreSQL INTERVAL units
    _DATEADD_UNIT_MAP = {
        'YEAR': 'year',
        'YYYY': 'year',
        'YY': 'year',
        'QUARTER': 'quarter',
        'QQ': 'quarter',
        'Q': 'quarter',
        'MONTH': 'month',
        'MM': 'month',
        'M': 'month',
        'WEEK': 'week',
        'WK': 'week',
        'WW': 'week',
        'DAY': 'day',
        'DD': 'day',
        'D': 'day',
        'HOUR': 'hour',
        'HH': 'hour',
        'MINUTE': 'minute',
        'MI': 'minute',
        'N': 'minute',
        'SECOND': 'second',
        'SS': 'second',
        'S': 'second',
        'MILLISECOND': 'millisecond',
        'MS': 'millisecond',
    }

    _DATEADD_PATTERN = re.compile(
        r'DATEADD\s*\(\s*(\w+)\s*,\s*([^,]+?)\s*,\s*([^)]+?)\s*\)',
        re.IGNORECASE,
    )

    _DATEDIFF_PATTERN = re.compile(
        r'DATEDIFF\s*\(\s*(\w+)\s*,\s*([^,]+?)\s*,\s*([^)]+?)\s*\)',
        re.IGNORECASE,
    )

    @staticmethod
    def convert_dateadd(content: str) -> Tuple[str, int]:
        """Convert DATEADD patterns to INTERVAL expressions.

        Args:
            content: SQL content to process

        Returns:
            Tuple of (modified_sql, count_of_conversions)
        """
        if 'DATEADD' not in content.upper():
            return content, 0

        count = 0

        def replace_dateadd(m: re.Match) -> str:
            nonlocal count
            count += 1
            unit_raw = m.group(1).strip().upper()
            offset = m.group(2).strip()
            date_expr = m.group(3).strip()

            # Map unit to PostgreSQL
            pg_unit = DateAddConverter._DATEADD_UNIT_MAP.get(unit_raw, unit_raw.lower())

            # Determine if offset is positive or negative
            # Handle negative numbers
            offset_str = offset.replace('+', '').strip()
            is_negative = offset.startswith('-')

            if is_negative:
                operator = '-'
                offset_num = offset_str[1:].strip() if offset_str.startswith('-') else offset_str
            else:
                operator = '+'
                offset_num = offset_str

            # Build INTERVAL expression
            return f'({date_expr} {operator} INTERVAL \'{offset_num} {pg_unit}\')'

        converted = DateAddConverter._DATEADD_PATTERN.sub(replace_dateadd, content)
        return converted, count

    @staticmethod
    def convert_datediff(content: str) -> Tuple[str, int]:
        """Convert DATEDIFF patterns to PostgreSQL date difference expressions.

        Args:
            content: SQL content to process

        Returns:
            Tuple of (modified_sql, count_of_conversions)
        """
        if 'DATEDIFF' not in content.upper():
            return content, 0

        count = 0

        def replace_datediff(m: re.Match) -> str:
            nonlocal count
            count += 1
            unit_raw = m.group(1).strip().upper()
            date1 = m.group(2).strip()
            date2 = m.group(3).strip()

            # For DAY, use simple date subtraction
            if unit_raw in ('DAY', 'DD', 'D'):
                return f'({date2}::DATE - {date1}::DATE)'

            # For other units, use EXTRACT(unit FROM (date2 - date1))
            pg_unit = DateAddConverter._DATEADD_UNIT_MAP.get(unit_raw, unit_raw.lower())
            return f'EXTRACT({pg_unit.upper()} FROM ({date2} - {date1}))'

        converted = DateAddConverter._DATEDIFF_PATTERN.sub(replace_datediff, content)
        return converted, count

    @staticmethod
    def apply_all(content: str) -> EnhancementResult:
        """Apply all DATEADD/DATEDIFF conversions.

        Args:
            content: SQL content to process

        Returns:
            EnhancementResult with modified SQL and stats
        """
        if 'DATEADD' not in content.upper() and 'DATEDIFF' not in content.upper():
            return EnhancementResult(sql=content, warnings=[], fixes_applied=0)

        warnings = []
        total_fixes = 0

        sql, count = DateAddConverter.convert_dateadd(content)
        total_fixes += count

        sql, count = DateAddConverter.convert_datediff(sql)
        total_fixes += count

        if total_fixes > 0:
            warnings.append(
                f'T-SQL DATEADD/DATEDIFF patterns converted to INTERVAL expressions ({total_fixes} changes). '
                'Review for correctness in edge cases (units, timezones).'
            )

        return EnhancementResult(sql=sql, warnings=warnings, fixes_applied=total_fixes)
