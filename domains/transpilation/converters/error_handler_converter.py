"""
Module: domains/transpilation/converters/error_handler_converter.py
Purpose: Converts T-SQL error handling functions to PL/pgSQL equivalents.
         Maps ERROR_MESSAGE → SQLERRM, ERROR_NUMBER → SQLSTATE, etc.
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
    """Result of applying error handler enhancements."""

    sql: str
    warnings: List[str] = field(default_factory=list)
    fixes_applied: int = 0


class ErrorHandlerConverter:
    """Handles T-SQL error function to PL/pgSQL conversion.

    Mappings:
    - ERROR_MESSAGE() → SQLERRM
    - ERROR_NUMBER() → SQLSTATE
    - ERROR_STATE() → SQLSTATE
    - ERROR_SEVERITY() → /* ⚠️ MANUAL REVIEW */
    - ERROR_LINE() → /* ⚠️ MANUAL REVIEW */
    - ERROR_PROCEDURE() → /* ⚠️ MANUAL REVIEW */
    - XACT_STATE() → /* ⚠️ MANUAL REVIEW */
    """

    # Error functions that map to PL/pgSQL equivalents
    _ERROR_FUNCTION_MAP = {
        'ERROR_MESSAGE': 'SQLERRM',
        'ERROR_NUMBER': 'SQLSTATE',
        'ERROR_STATE': 'SQLSTATE',
    }

    # Error functions with no direct PG equivalent
    _UNSUPPORTED_ERROR_FUNCTIONS = [
        'ERROR_SEVERITY',
        'ERROR_LINE',
        'ERROR_PROCEDURE',
        'XACT_STATE',
    ]

    @staticmethod
    def convert_error_functions(content: str) -> Tuple[str, int]:
        """Convert supported T-SQL error functions to PL/pgSQL equivalents.

        Args:
            content: SQL content to process

        Returns:
            Tuple of (modified_sql, count_of_conversions)
        """
        if not any(f.upper() in content.upper() for f in ErrorHandlerConverter._ERROR_FUNCTION_MAP):
            return content, 0

        count = 0
        converted = content

        for tsql_func, pg_equivalent in ErrorHandlerConverter._ERROR_FUNCTION_MAP.items():
            pattern = re.compile(
                f'{tsql_func}\\s*\\(\\s*\\)',
                re.IGNORECASE,
            )

            matches = list(pattern.finditer(converted))
            if matches:
                converted = pattern.sub(pg_equivalent, converted)
                count += len(matches)

        return converted, count

    @staticmethod
    def convert_unsupported_error_functions(content: str) -> Tuple[str, int]:
        """Flag unsupported T-SQL error functions for manual review.

        Args:
            content: SQL content to process

        Returns:
            Tuple of (modified_sql, count_of_conversions)
        """
        count = 0
        converted = content

        for tsql_func in ErrorHandlerConverter._UNSUPPORTED_ERROR_FUNCTIONS:
            pattern = re.compile(
                f'{tsql_func}\\s*\\(\\s*\\)',
                re.IGNORECASE,
            )

            matches = list(pattern.finditer(converted))
            if matches:
                # Replace with a comment
                comment = f'/* ⚠️ MANUAL REVIEW: {tsql_func}() has no direct PG equivalent */ NULL'
                converted = pattern.sub(comment, converted)
                count += len(matches)

        return converted, count

    @staticmethod
    def apply_all(content: str) -> EnhancementResult:
        """Apply all error handler conversions.

        Order:
        1. Convert supported error functions
        2. Flag unsupported error functions

        Args:
            content: SQL content to process

        Returns:
            EnhancementResult with modified SQL and stats
        """
        if not any(f.upper() in content.upper()
                  for f in (list(ErrorHandlerConverter._ERROR_FUNCTION_MAP.keys()) +
                           ErrorHandlerConverter._UNSUPPORTED_ERROR_FUNCTIONS)):
            return EnhancementResult(sql=content, warnings=[], fixes_applied=0)

        warnings = []
        total_fixes = 0

        # Convert supported functions
        sql, count = ErrorHandlerConverter.convert_error_functions(content)
        total_fixes += count

        # Flag unsupported functions
        sql, count = ErrorHandlerConverter.convert_unsupported_error_functions(sql)
        total_fixes += count

        if total_fixes > 0:
            warnings.append(
                f'T-SQL error handling functions converted ({total_fixes} changes). '
                'Review MANUAL REVIEW comments for functions without direct PG equivalents.'
            )

        return EnhancementResult(sql=sql, warnings=warnings, fixes_applied=total_fixes)
