"""
Module: domains/transpilation/converters/cursor_converter.py
Purpose: Converts T-SQL CURSOR operations to PL/pgSQL REFCURSOR pattern.
         Handles DECLARE CURSOR, OPEN, FETCH, FETCH_STATUS loops, CLOSE, and DEALLOCATE.
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
    """Result of applying cursor enhancements."""

    sql: str
    warnings: List[str] = field(default_factory=list)
    fixes_applied: int = 0


class CursorConverter:
    """Handles T-SQL CURSOR to PL/pgSQL REFCURSOR conversion.

    Converts T-SQL cursor patterns:
    - DECLARE @cur CURSOR FOR SELECT ... → DECLARE v_cur REFCURSOR;
    - OPEN @cur → OPEN v_cur FOR SELECT ...;
    - FETCH NEXT FROM @cur INTO @vars → FETCH NEXT FROM v_cur INTO v_vars;
    - WHILE @@FETCH_STATUS = 0 → LOOP ... EXIT WHEN NOT FOUND;
    - CLOSE @cur → CLOSE v_cur;
    - DEALLOCATE @cur → (removed, commented as PG handles automatically)
    """

    # Pattern to find DECLARE @<name> CURSOR
    _DECLARE_CURSOR_PATTERN = re.compile(
        r'DECLARE\s+(@\w+)\s+CURSOR\s+(?:FOR\s+(SELECT\s+.+?)(?=;|$))?',
        re.IGNORECASE | re.DOTALL,
    )

    # Pattern to find OPEN @<name>
    _OPEN_CURSOR_PATTERN = re.compile(
        r'OPEN\s+(@\w+)(?:\s+FOR\s+(SELECT\s+.+?))?(?=;)',
        re.IGNORECASE,
    )

    # Pattern to find FETCH NEXT FROM @<name> INTO @<vars>
    _FETCH_PATTERN = re.compile(
        r'FETCH\s+(?:NEXT\s+)?FROM\s+(@\w+)\s+INTO\s+((?:@\w+(?:\s*,\s*@\w+)*)?);',
        re.IGNORECASE,
    )

    # Pattern to find WHILE @@FETCH_STATUS = 0
    _FETCH_STATUS_LOOP_PATTERN = re.compile(
        r'WHILE\s+@@FETCH_STATUS\s*=\s*0\s*BEGIN',
        re.IGNORECASE,
    )

    # Pattern to find CLOSE @<name>
    _CLOSE_CURSOR_PATTERN = re.compile(
        r'CLOSE\s+(@\w+)',
        re.IGNORECASE,
    )

    # Pattern to find DEALLOCATE @<name>
    _DEALLOCATE_CURSOR_PATTERN = re.compile(
        r'DEALLOCATE\s+(@\w+)',
        re.IGNORECASE,
    )

    @staticmethod
    def _convert_var_prefix(tsql_var: str) -> str:
        """Convert @VarName to v_VarName or v_var_name."""
        if tsql_var.startswith('@'):
            # Remove @ and keep camelCase with v_ prefix
            name = tsql_var[1:]
            return f'v_{name}'
        return tsql_var

    @staticmethod
    def convert_declare(content: str) -> Tuple[str, int]:
        """Convert DECLARE @cur CURSOR FOR SELECT to DECLARE v_cur REFCURSOR.

        Args:
            content: SQL content to process

        Returns:
            Tuple of (modified_sql, count_of_conversions)
        """
        if 'CURSOR' not in content.upper():
            return content, 0

        matches = list(CursorConverter._DECLARE_CURSOR_PATTERN.finditer(content))

        def replace_declare(m: re.Match) -> str:
            cursor_var = m.group(1)  # @CursorName
            select_stmt = m.group(2)  # SELECT ... if present
            converted_var = CursorConverter._convert_var_prefix(cursor_var)

            if select_stmt:
                # DECLARE with FOR SELECT
                return f'DECLARE {converted_var} REFCURSOR;\n-- REFCURSOR select for: {select_stmt.strip()}'
            else:
                # Just DECLARE cursor
                return f'DECLARE {converted_var} REFCURSOR;'

        converted = CursorConverter._DECLARE_CURSOR_PATTERN.sub(replace_declare, content)
        count = len(matches)
        return converted, count

    @staticmethod
    def convert_open(content: str) -> Tuple[str, int]:
        """Convert OPEN @cur FOR SELECT to OPEN v_cur FOR SELECT.

        Args:
            content: SQL content to process

        Returns:
            Tuple of (modified_sql, count_of_conversions)
        """
        if 'OPEN' not in content.upper():
            return content, 0

        matches = list(CursorConverter._OPEN_CURSOR_PATTERN.finditer(content))

        def replace_open(m: re.Match) -> str:
            cursor_var = m.group(1)  # @CursorName
            select_stmt = m.group(2)  # SELECT ... if present
            converted_var = CursorConverter._convert_var_prefix(cursor_var)

            if select_stmt:
                return f'OPEN {converted_var} FOR {select_stmt.strip()}'
            else:
                return f'OPEN {converted_var}'

        converted = CursorConverter._OPEN_CURSOR_PATTERN.sub(replace_open, content)
        count = len(matches)
        return converted, count

    @staticmethod
    def convert_fetch(content: str) -> Tuple[str, int]:
        """Convert FETCH NEXT FROM @cur INTO @vars to PL/pgSQL syntax.

        Args:
            content: SQL content to process

        Returns:
            Tuple of (modified_sql, count_of_conversions)
        """
        if 'FETCH' not in content.upper():
            return content, 0

        matches = list(CursorConverter._FETCH_PATTERN.finditer(content))

        def replace_fetch(m: re.Match) -> str:
            cursor_var = m.group(1)  # @CursorName
            into_vars = m.group(2)  # @var1, @var2, ...
            converted_cursor = CursorConverter._convert_var_prefix(cursor_var)

            # Convert variable list
            var_list = into_vars.strip()
            if var_list:
                # Split by comma and convert each @var to v_var
                vars_array = [v.strip() for v in var_list.split(',')]
                converted_vars = ', '.join(CursorConverter._convert_var_prefix(v) for v in vars_array)
                return f'FETCH NEXT FROM {converted_cursor} INTO {converted_vars};'
            else:
                return f'FETCH NEXT FROM {converted_cursor};'

        converted = CursorConverter._FETCH_PATTERN.sub(replace_fetch, content)
        count = len(matches)
        return converted, count

    @staticmethod
    def convert_fetch_status_loop(content: str) -> Tuple[str, int]:
        """Convert WHILE @@FETCH_STATUS = 0 BEGIN...END to LOOP...EXIT WHEN.

        Args:
            content: SQL content to process

        Returns:
            Tuple of (modified_sql, count_of_conversions)
        """
        if '@@FETCH_STATUS' not in content.upper():
            return content, 0

        count = 0

        def replace_while_fetch_status(m: re.Match) -> str:
            nonlocal count
            count += 1
            # Replace WHILE @@FETCH_STATUS = 0 BEGIN with LOOP
            return 'LOOP'

        converted = CursorConverter._FETCH_STATUS_LOOP_PATTERN.sub(replace_while_fetch_status, content)

        # Also replace END (closing the while block) with EXIT WHEN NOT FOUND; END LOOP;
        # Look for END statements that are likely closing the while block
        converted = re.sub(
            r'\bEND\b\s*$',
            'EXIT WHEN NOT FOUND;\n    END LOOP;',
            converted,
            flags=re.IGNORECASE | re.MULTILINE,
        )

        return converted, count

    @staticmethod
    def remove_close(content: str) -> Tuple[str, int]:
        """Convert CLOSE @cur to PL/pgSQL CLOSE syntax.

        Args:
            content: SQL content to process

        Returns:
            Tuple of (modified_sql, count_of_conversions)
        """
        if 'CLOSE' not in content.upper():
            return content, 0

        matches = list(CursorConverter._CLOSE_CURSOR_PATTERN.finditer(content))

        def replace_close(m: re.Match) -> str:
            cursor_var = m.group(1)
            converted_var = CursorConverter._convert_var_prefix(cursor_var)
            return f'CLOSE {converted_var}'

        converted = CursorConverter._CLOSE_CURSOR_PATTERN.sub(replace_close, content)
        count = len(matches)
        return converted, count

    @staticmethod
    def remove_deallocate(content: str) -> Tuple[str, int]:
        """Remove or comment DEALLOCATE (PostgreSQL handles automatically).

        Args:
            content: SQL content to process

        Returns:
            Tuple of (modified_sql, count_of_conversions)
        """
        if 'DEALLOCATE' not in content.upper():
            return content, 0

        matches = list(CursorConverter._DEALLOCATE_CURSOR_PATTERN.finditer(content))

        def replace_deallocate(m: re.Match) -> str:
            # Comment out the DEALLOCATE (PG has no equivalent)
            return f'-- DEALLOCATE {m.group(1)}  (handled automatically by PostgreSQL)'

        converted = CursorConverter._DEALLOCATE_CURSOR_PATTERN.sub(replace_deallocate, content)
        count = len(matches)
        return converted, count

    @staticmethod
    def apply_all(content: str) -> EnhancementResult:
        """Apply all cursor conversion steps in sequence.

        Order:
        1. Convert DECLARE CURSOR to REFCURSOR
        2. Convert OPEN statements
        3. Convert FETCH statements
        4. Convert FETCH_STATUS loops
        5. Convert CLOSE statements
        6. Remove DEALLOCATE statements

        Args:
            content: SQL content to process

        Returns:
            EnhancementResult with modified SQL and stats
        """
        if 'CURSOR' not in content.upper():
            return EnhancementResult(sql=content, warnings=[], fixes_applied=0)

        warnings = []
        total_fixes = 0

        # Step 1: Declare
        sql, count = CursorConverter.convert_declare(content)
        total_fixes += count

        # Step 2: Open
        sql, count = CursorConverter.convert_open(sql)
        total_fixes += count

        # Step 3: Fetch
        sql, count = CursorConverter.convert_fetch(sql)
        total_fixes += count

        # Step 4: Fetch Status Loop
        sql, count = CursorConverter.convert_fetch_status_loop(sql)
        total_fixes += count

        # Step 5: Close
        sql, count = CursorConverter.remove_close(sql)
        total_fixes += count

        # Step 6: Deallocate
        sql, count = CursorConverter.remove_deallocate(sql)
        total_fixes += count

        if total_fixes > 0:
            warnings.append(
                f'T-SQL CURSOR converted to PL/pgSQL REFCURSOR pattern ({total_fixes} changes). '
                'Review CURSOR VARYING OUTPUT and complex cursor parameters for manual adjustment.'
            )

        return EnhancementResult(
            sql=sql,
            warnings=warnings,
            fixes_applied=total_fixes,
        )
