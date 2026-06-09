"""
Module: domains/transpilation/phase4_enhancements.py
Purpose: Orchestrates Phase 4 advanced conversion fixes (rowcount, cursor, dynamic SQL, errors, dateadd, control flow).
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List

from domains.transpilation.converters.control_flow_fixer import ControlFlowFixer
from domains.transpilation.converters.cursor_converter import CursorConverter
from domains.transpilation.converters.cursor_handler import CursorHandler
from domains.transpilation.converters.dateadd_converter import DateAddConverter
from domains.transpilation.converters.dynamic_sql_converter import DynamicSqlConverter
from domains.transpilation.converters.error_handler_converter import ErrorHandlerConverter
from domains.transpilation.converters.merge_converter import MergeConverter
from domains.transpilation.converters.output_converter import OutputConverter
from domains.transpilation.converters.rowcount_converter import RowcountConverter


@dataclass
class EnhancementResult:
    """Result of applying Phase 4 enhancements."""

    sql: str
    warnings: List[str] = field(default_factory=list)
    fixes_applied: int = 0


class Phase4Enhancements:
    """Phase 4: Advanced patterns — rowcount, cursor, dynamic SQL, errors, dateadd, control flow.

    Applies six specialized converters in sequence to handle complex T-SQL → PL/pgSQL patterns.
    """

    @staticmethod
    def fix_rowcount(content: str) -> tuple[str, int]:
        """Apply RowcountConverter enhancements."""
        result = RowcountConverter.apply_all(content)
        return result.sql, result.fixes_applied

    @staticmethod
    def convert_cursors(content: str) -> tuple[str, int]:
        """Apply CursorConverter enhancements."""
        result = CursorConverter.apply_all(content)
        return result.sql, result.fixes_applied

    @staticmethod
    def convert_dynamic_sql(content: str) -> tuple[str, int]:
        """Apply DynamicSqlConverter enhancements."""
        result = DynamicSqlConverter.apply_all(content)
        return result.sql, result.fixes_applied

    @staticmethod
    def convert_error_functions(content: str) -> tuple[str, int]:
        """Apply ErrorHandlerConverter enhancements."""
        result = ErrorHandlerConverter.apply_all(content)
        return result.sql, result.fixes_applied

    @staticmethod
    def fix_dateadd(content: str) -> tuple[str, int]:
        """Apply DateAddConverter enhancements."""
        result = DateAddConverter.apply_all(content)
        return result.sql, result.fixes_applied

    @staticmethod
    def fix_control_flow(content: str) -> tuple[str, int]:
        """Apply ControlFlowFixer enhancements."""
        result = ControlFlowFixer.apply_all(content)
        return result.sql, result.fixes_applied

    @staticmethod
    def convert_merge(content: str) -> tuple[str, int]:
        """Apply MergeConverter enhancements (MERGE → INSERT ON CONFLICT)."""
        result = MergeConverter.apply_all(content)
        return result.sql, int(result.success)

    @staticmethod
    def convert_output(content: str) -> tuple[str, int]:
        """Apply OutputConverter enhancements (OUTPUT → RETURNING)."""
        result = OutputConverter.apply_all(content)
        return result.sql, int(result.success)

    @staticmethod
    def convert_cursor_advanced(content: str) -> tuple[str, int]:
        """Apply CursorHandler for advanced CURSOR patterns.

        CursorHandler replaces the entire input when it finds a cursor.  Skip
        wrapped PL/pgSQL objects and full CREATE PROCEDURE/FUNCTION bodies.
        """
        if re.search(
            r"\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:PROCEDURE|FUNCTION)\b",
            content,
            re.IGNORECASE,
        ):
            return content, 0
        if "$$" in content and "LANGUAGE PLPGSQL" in content.upper():
            return content, 0
        result = CursorHandler.apply_all(content)
        if result.success and len(result.sql.strip()) < len(content.strip()) * 0.6:
            return content, 0
        return result.sql, int(result.success)

    @staticmethod
    def apply_all(content: str) -> EnhancementResult:
        """Apply all Phase 4 enhancements in sequence.

        Order:
        1. Fix @@ROWCOUNT patterns
        2. Convert MERGE to INSERT ON CONFLICT
        3. Convert OUTPUT to RETURNING
        4. Convert CURSOR operations (advanced)
        5. Convert existing CURSOR operations (legacy)
        6. Convert dynamic SQL (EXEC/sp_executesql)
        7. Convert error functions
        8. Fix DATEADD/DATEDIFF
        9. Fix control flow syntax

        Args:
            content: SQL content to process

        Returns:
            EnhancementResult with modified SQL and stats
        """
        warnings = []
        total_fixes = 0

        # Step 1: Rowcount
        sql, count = Phase4Enhancements.fix_rowcount(content)
        total_fixes += count

        # Step 2: MERGE → INSERT ON CONFLICT
        sql, count = Phase4Enhancements.convert_merge(sql)
        total_fixes += count

        # Step 3: OUTPUT → RETURNING
        sql, count = Phase4Enhancements.convert_output(sql)
        total_fixes += count

        # Step 4-5: CURSOR — only on bare T-SQL snippets (not wrapped PL/pgSQL bodies).
        if not (
            re.search(r"\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:PROCEDURE|FUNCTION)\b", sql, re.IGNORECASE)
            or ("$$" in sql and "LANGUAGE PLPGSQL" in sql.upper())
        ):
            sql, count = Phase4Enhancements.convert_cursor_advanced(sql)
            total_fixes += count
            sql, count = Phase4Enhancements.convert_cursors(sql)
            total_fixes += count

        # Step 6: Dynamic SQL
        sql, count = Phase4Enhancements.convert_dynamic_sql(sql)
        total_fixes += count

        # Step 7: Error functions
        sql, count = Phase4Enhancements.convert_error_functions(sql)
        total_fixes += count

        # Step 8: DateAdd
        sql, count = Phase4Enhancements.fix_dateadd(sql)
        total_fixes += count

        # Step 9: Control flow
        sql, count = Phase4Enhancements.fix_control_flow(sql)
        total_fixes += count

        if total_fixes > 0:
            warnings.append(
                f'Phase 4: Advanced patterns converted ({total_fixes} total fixes). '
                'Review warnings from individual converters for details.'
            )

        return EnhancementResult(sql=sql, warnings=warnings, fixes_applied=total_fixes)
