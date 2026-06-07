"""
Module: domains/transpilation/converters/rowcount_converter.py
Purpose: Converts @@ROWCOUNT pattern to PostgreSQL GET DIAGNOSTICS + v_row_count variable.
         Injects GET DIAGNOSTICS after DML statements followed by @@ROWCOUNT checks,
         then replaces all @@ROWCOUNT references with v_row_count.
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
    """Result of applying rowcount enhancements."""

    sql: str
    warnings: List[str] = field(default_factory=list)
    fixes_applied: int = 0


class RowcountConverter:
    """Handles @@ROWCOUNT → GET DIAGNOSTICS + v_row_count conversion.

    This converter:
    1. Detects DML (INSERT/UPDATE/DELETE) statements followed by @@ROWCOUNT checks
    2. Injects GET DIAGNOSTICS v_row_count = ROW_COUNT; after the DML statement
    3. Replaces all @@ROWCOUNT references with v_row_count
    """

    # Regex to find DML statements: UPDATE/INSERT/DELETE followed by any content and semicolon
    _DML_PATTERN = re.compile(
        r'((?:UPDATE|INSERT|DELETE)\b[^;]+;)',
        re.IGNORECASE | re.DOTALL,
    )

    # Regex to detect @@ROWCOUNT checks (case-insensitive)
    _ROWCOUNT_CHECK_PATTERN = re.compile(
        r'@@ROWCOUNT',
        re.IGNORECASE,
    )

    @staticmethod
    def inject_get_diagnostics(content: str) -> Tuple[str, int]:
        """Inject GET DIAGNOSTICS after DML statements followed by @@ROWCOUNT checks.

        Scans for DML statements (UPDATE/INSERT/DELETE) that appear before
        a @@ROWCOUNT check within a 10-line window. For each match, injects:
        GET DIAGNOSTICS v_row_count = ROW_COUNT;

        Args:
            content: SQL content to process

        Returns:
            Tuple of (modified_sql, count_of_injections)
        """
        if '@@ROWCOUNT' not in content.upper():
            return content, 0

        lines = content.split('\n')
        result_lines = []
        fix_count = 0
        i = 0

        while i < len(lines):
            line = lines[i]
            result_lines.append(line)

            # Check if line contains a DML statement ending with semicolon
            dml_match = re.search(
                r'(UPDATE|INSERT|DELETE)\b.*?;',
                line,
                re.IGNORECASE,
            )

            if dml_match:
                # Look ahead up to 10 lines for a @@ROWCOUNT check
                found_rowcount = False
                for lookahead in range(1, min(10, len(lines) - i)):
                    lookahead_line = lines[i + lookahead]
                    if '@@ROWCOUNT' in lookahead_line.upper():
                        found_rowcount = True
                        break

                if found_rowcount:
                    # Inject GET DIAGNOSTICS after this DML line
                    result_lines.append('GET DIAGNOSTICS v_row_count = ROW_COUNT;')
                    fix_count += 1

            i += 1

        return '\n'.join(result_lines), fix_count

    @staticmethod
    def replace_rowcount_refs(content: str) -> Tuple[str, int]:
        """Replace all @@ROWCOUNT references with v_row_count.

        Args:
            content: SQL content to process

        Returns:
            Tuple of (modified_sql, count_of_replacements)
        """
        if '@@ROWCOUNT' not in content.upper():
            return content, 0

        # Count occurrences before replacement
        pattern = re.compile(r'@@ROWCOUNT', re.IGNORECASE)
        matches = list(pattern.finditer(content))
        count = len(matches)

        # Replace all @@ROWCOUNT with v_row_count
        converted = pattern.sub('v_row_count', content)

        return converted, count

    @staticmethod
    def apply_all(content: str) -> EnhancementResult:
        """Apply all rowcount enhancements (inject + replace) in sequence.

        Args:
            content: SQL content to process

        Returns:
            EnhancementResult with modified SQL and stats
        """
        # Step 1: Inject GET DIAGNOSTICS after DML statements
        injected_sql, inject_count = RowcountConverter.inject_get_diagnostics(content)

        # Step 2: Replace @@ROWCOUNT references
        final_sql, replace_count = RowcountConverter.replace_rowcount_refs(injected_sql)

        total_fixes = inject_count + replace_count
        warnings = []

        if total_fixes > 0:
            warnings.append(
                f'@@ROWCOUNT pattern converted to GET DIAGNOSTICS + v_row_count ({total_fixes} changes)'
            )

        return EnhancementResult(
            sql=final_sql,
            warnings=warnings,
            fixes_applied=total_fixes,
        )
