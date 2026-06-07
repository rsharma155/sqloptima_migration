"""
Module: domains/transpilation/converters/control_flow_fixer.py
Purpose: Fixes T-SQL/PL/pgSQL control flow syntax mixing issues.
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
    """Result of applying control flow enhancements."""

    sql: str
    warnings: List[str] = field(default_factory=list)
    fixes_applied: int = 0


class ControlFlowFixer:
    """Fixes mixed T-SQL/PL/pgSQL control flow syntax.

    Fixes:
    - IF cond BEGIN → IF cond THEN
    - ELSE IF → ELSIF
    - END -- IF/LOOP → END IF; / END LOOP;
    - bare RETURN → RETURN;
    """

    _IF_BEGIN_PATTERN = re.compile(
        r'IF\s+(.+?)\s+BEGIN\b',
        re.IGNORECASE,
    )

    _ELSE_IF_PATTERN = re.compile(
        r'ELSE\s+IF\b',
        re.IGNORECASE,
    )

    _END_LABEL_PATTERN = re.compile(
        r'END\s+--\s*(IF|LOOP|WHILE)',
        re.IGNORECASE,
    )

    _BARE_RETURN_PATTERN = re.compile(
        r'\bRETURN\s*\n',
        re.IGNORECASE,
    )

    @staticmethod
    def fix_if_begin(content: str) -> Tuple[str, int]:
        """Convert IF cond BEGIN to IF cond THEN.

        Args:
            content: SQL content to process

        Returns:
            Tuple of (modified_sql, count_of_conversions)
        """
        if 'BEGIN' not in content.upper():
            return content, 0

        count = 0

        def replace_if_begin(m: re.Match) -> str:
            nonlocal count
            count += 1
            condition = m.group(1).strip()
            return f'IF {condition} THEN'

        converted = ControlFlowFixer._IF_BEGIN_PATTERN.sub(replace_if_begin, content)
        return converted, count

    @staticmethod
    def fix_else_if(content: str) -> Tuple[str, int]:
        """Convert ELSE IF to ELSIF.

        Args:
            content: SQL content to process

        Returns:
            Tuple of (modified_sql, count_of_conversions)
        """
        if 'ELSE' not in content.upper() or 'IF' not in content.upper():
            return content, 0

        matches = list(ControlFlowFixer._ELSE_IF_PATTERN.finditer(content))
        count = len(matches)

        if count > 0:
            converted = ControlFlowFixer._ELSE_IF_PATTERN.sub('ELSIF', content)
        else:
            converted = content

        return converted, count

    @staticmethod
    def fix_end_labels(content: str) -> Tuple[str, int]:
        """Fix END -- IF/LOOP labels to END IF; / END LOOP;

        Args:
            content: SQL content to process

        Returns:
            Tuple of (modified_sql, count_of_conversions)
        """
        if 'END' not in content.upper():
            return content, 0

        matches = list(ControlFlowFixer._END_LABEL_PATTERN.finditer(content))
        count = len(matches)

        if count > 0:
            def replace_end_label(m: re.Match) -> str:
                label = m.group(1).strip().upper()
                return f'END {label};'

            converted = ControlFlowFixer._END_LABEL_PATTERN.sub(replace_end_label, content)
        else:
            converted = content

        return converted, count

    @staticmethod
    def fix_bare_return(content: str) -> Tuple[str, int]:
        """Add semicolon to bare RETURN statements.

        Args:
            content: SQL content to process

        Returns:
            Tuple of (modified_sql, count_of_conversions)
        """
        if 'RETURN' not in content.upper():
            return content, 0

        matches = list(ControlFlowFixer._BARE_RETURN_PATTERN.finditer(content))
        count = len(matches)

        if count > 0:
            converted = ControlFlowFixer._BARE_RETURN_PATTERN.sub('RETURN;\n', content)
        else:
            converted = content

        return converted, count

    @staticmethod
    def apply_all(content: str) -> EnhancementResult:
        """Apply all control flow fixes.

        Order:
        1. Fix IF BEGIN → IF THEN
        2. Fix ELSE IF → ELSIF
        3. Fix END labels
        4. Fix bare RETURN

        Args:
            content: SQL content to process

        Returns:
            EnhancementResult with modified SQL and stats
        """
        if not any(kw.upper() in content.upper() for kw in ['IF', 'ELSE', 'END', 'RETURN']):
            return EnhancementResult(sql=content, warnings=[], fixes_applied=0)

        warnings = []
        total_fixes = 0

        sql, count = ControlFlowFixer.fix_if_begin(content)
        total_fixes += count

        sql, count = ControlFlowFixer.fix_else_if(sql)
        total_fixes += count

        sql, count = ControlFlowFixer.fix_end_labels(sql)
        total_fixes += count

        sql, count = ControlFlowFixer.fix_bare_return(sql)
        total_fixes += count

        if total_fixes > 0:
            warnings.append(
                f'T-SQL control flow syntax normalized to PL/pgSQL ({total_fixes} changes). '
                'Review IF/ELSE/END structures for correctness.'
            )

        return EnhancementResult(sql=sql, warnings=warnings, fixes_applied=total_fixes)
