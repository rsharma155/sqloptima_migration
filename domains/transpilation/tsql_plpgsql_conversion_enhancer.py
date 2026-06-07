"""
Module: domains/transpilation/tsql_plpgsql_conversion_enhancer.py
Purpose: Enhance T-SQL to PL/pgSQL conversion with advanced fixes through four phases:
         - Phase 1: Parameter formatting, variable prefixes, function mapping
         - Phase 2: Hint removal, pattern flagging
         - Phase 3: Transaction control, error handling, syntax cleanup
         - Phase 4: Advanced patterns (rowcount, cursor, dynamic SQL, errors, dateadd, control flow)

         This module provides multiple enhancement classes that are applied sequentially
         to convert SQL Server stored procedures to PostgreSQL PL/pgSQL, improving
         compatibility and reducing manual fixes needed.

Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Tuple

from domains.transpilation.phase4_enhancements import Phase4Enhancements


@dataclass
class EnhancementResult:
    """Result of applying phase enhancements."""

    sql: str
    warnings: List[str] = field(default_factory=list)
    fixes_applied: int = 0


class Phase1Enhancements:
    """Phase 1: Quick Wins - Parameter and variable fixes."""

    @staticmethod
    def fix_parameter_commas(content: str) -> Tuple[str, int]:
        """Collapse erroneous double commas in parameter lists.

        A doubled comma (optionally whitespace/newline separated) is never valid
        SQL, so every ``,,`` collapses to ``,``. This covers both the
        ``DEFAULT NULL,,`` and the bare ``VARCHAR(50),,`` forms.
        """
        pattern = r',\s*,'
        matches = len(re.findall(pattern, content))
        while re.search(pattern, content):
            content = re.sub(pattern, ',', content)
        return content, matches

    @staticmethod
    def fix_variable_prefixes(content: str) -> Tuple[str, int]:
        """Strip @ prefix from variable names and replace with p_ or v_."""
        # Extract parameter names to distinguish from local variables
        param_pattern = r'(?:IN|INOUT|OUT)\s+p_(\w+)\s+'
        params = set(re.findall(param_pattern, content, re.IGNORECASE))

        # Use lambda to determine prefix based on parameter list
        fixed = re.sub(
            r'(?<!@)@([a-zA-Z_]\w*)(?!@)',
            lambda m: f"p_{m.group(1)}" if m.group(1) in params else f"v_{m.group(1)}",
            content
        )

        matches = len(re.findall(r'(?<!@)@([a-zA-Z_]\w*)(?!@)', content))
        return fixed, matches

    @staticmethod
    def fix_scope_identity(content: str) -> Tuple[str, int]:
        """Convert SCOPE_IDENTITY() to LASTVAL()."""
        pattern = r'\bSCOPE_IDENTITY\s*\(\)'
        matches = len(re.findall(pattern, content, re.IGNORECASE))

        if matches > 0:
            content = re.sub(pattern, 'LASTVAL()', content, flags=re.IGNORECASE)

        return content, matches

    @staticmethod
    def apply_all(content: str) -> EnhancementResult:
        """Apply all Phase 1 enhancements."""
        total_fixes = 0

        # Fix parameter commas
        content, fixes = Phase1Enhancements.fix_parameter_commas(content)
        total_fixes += fixes

        # Fix variable prefixes
        content, fixes = Phase1Enhancements.fix_variable_prefixes(content)
        total_fixes += fixes

        # Fix SCOPE_IDENTITY
        content, fixes = Phase1Enhancements.fix_scope_identity(content)
        total_fixes += fixes

        return EnhancementResult(sql=content, fixes_applied=total_fixes)


class Phase2Enhancements:
    """Phase 2: Medium Complexity - Hints removal and pattern flagging."""

    @staticmethod
    def remove_with_hints(content: str) -> Tuple[str, int]:
        """Remove T-SQL WITH hints like (NOLOCK, ROWLOCK, XLOCK, INDEX)."""
        pattern = r'\s+WITH\s*\(\s*[A-Z_()]+(?:\s*,\s*[A-Z_()]+)*\s*\)'
        matches = len(re.findall(pattern, content, re.IGNORECASE))

        if matches > 0:
            content = re.sub(pattern, '', content, flags=re.IGNORECASE)

        return content, matches

    @staticmethod
    def remove_option_hints(content: str) -> Tuple[str, int]:
        """Remove OPTION (MAXDOP, RECOMPILE, etc.) hints."""
        pattern = r'\s+OPTION\s*\(\s*[^)]*\)'
        matches = len(re.findall(pattern, content, re.IGNORECASE))

        if matches > 0:
            content = re.sub(pattern, '', content, flags=re.IGNORECASE)

        return content, matches

    @staticmethod
    def flag_complex_patterns(content: str) -> Tuple[str, int]:
        """Flag complex patterns that need manual review."""
        flags_added = 0

        # Flag MERGE statements
        if re.search(r'\bMERGE\s+', content, re.IGNORECASE):
            if '-- CRITICAL: PostgreSQL does not support MERGE' not in content:
                content = re.sub(
                    r'(\bMERGE\s+)',
                    r'-- CRITICAL: PostgreSQL does not support MERGE\n    -- Convert to INSERT ON CONFLICT\n    \1',
                    content,
                    flags=re.IGNORECASE,
                    count=1
                )
                flags_added += 1

        # Flag CURSOR operations
        if re.search(r'\bCURSOR\s+', content, re.IGNORECASE) and 'REFCURSOR' in content:
            if '-- MANUAL: REFCURSOR' not in content:
                flags_added += 1

        return content, flags_added

    @staticmethod
    def apply_all(content: str) -> EnhancementResult:
        """Apply all Phase 2 enhancements."""
        total_fixes = 0

        # Remove hints
        content, fixes = Phase2Enhancements.remove_with_hints(content)
        total_fixes += fixes

        content, fixes = Phase2Enhancements.remove_option_hints(content)
        total_fixes += fixes

        # Flag complex patterns
        content, fixes = Phase2Enhancements.flag_complex_patterns(content)
        total_fixes += fixes

        return EnhancementResult(sql=content, fixes_applied=total_fixes)


class Phase3Enhancements:
    """Phase 3: Complex Patterns - Transaction control, error handling, cleanup."""

    @staticmethod
    def fix_transaction_control(content: str) -> Tuple[str, int]:
        """Convert T-SQL transaction syntax to PostgreSQL."""
        fixes = 0

        # BEGIN TRANSACTION → BEGIN;
        if 'BEGIN TRANSACTION' in content:
            content = re.sub(
                r'BEGIN\s+TRANSACTION\s*;?',
                'BEGIN;',
                content,
                flags=re.IGNORECASE
            )
            fixes += 1

        # COMMIT TRANSACTION → COMMIT;
        if 'COMMIT TRANSACTION' in content:
            content = re.sub(
                r'COMMIT\s+TRANSACTION\s*;?',
                'COMMIT;',
                content,
                flags=re.IGNORECASE
            )
            fixes += 1

        # ROLLBACK TRANSACTION → ROLLBACK;
        if 'ROLLBACK TRANSACTION' in content:
            content = re.sub(
                r'ROLLBACK\s+TRANSACTION\s*;?',
                'ROLLBACK;',
                content,
                flags=re.IGNORECASE
            )
            fixes += 1

        return content, fixes

    @staticmethod
    def convert_error_handling(content: str) -> Tuple[str, int]:
        """Convert T-SQL error handling to PostgreSQL."""
        fixes = 0

        # RAISERROR('message', severity, state) → RAISE EXCEPTION 'message'
        pattern = r"RAISERROR\s*\(\s*N?'([^']+)'\s*,\s*\d+\s*,\s*\d+\s*\)"
        matches = len(re.findall(pattern, content, re.IGNORECASE))

        if matches > 0:
            content = re.sub(
                pattern,
                lambda m: f"RAISE EXCEPTION '{m.group(1)}'",
                content,
                flags=re.IGNORECASE
            )
            fixes += matches

        # THROW → RAISE EXCEPTION
        if 'THROW' in content:
            pattern = r'THROW\s+(\d+)\s*,\s*N?\'([^\']+)\'\s*,\s*\d+'
            matches = len(re.findall(pattern, content, re.IGNORECASE))
            if matches > 0:
                content = re.sub(
                    pattern,
                    lambda m: f"RAISE EXCEPTION '{m.group(2)}'",
                    content,
                    flags=re.IGNORECASE
                )
                fixes += matches

        return content, fixes

    @staticmethod
    def remove_duplicates(content: str) -> Tuple[str, int]:
        """Remove consecutive duplicate statements.

        A statement line (DML or ``RAISE``) that is byte-for-byte identical
        (after trimming surrounding whitespace) to the previous kept statement
        line is treated as an accidental duplicate and dropped. Only *adjacent*
        duplicates are removed, so distinct statements that merely repeat later
        in the body are preserved.
        """
        stmt_re = re.compile(r'^\s*(UPDATE|DELETE|INSERT|RAISE)\b', re.IGNORECASE)
        lines = content.split('\n')
        result: list[str] = []
        duplicates = 0
        last_stmt: str | None = None  # stripped form of the last kept statement

        for line in lines:
            stripped = line.strip()
            if stripped and stmt_re.match(line) and stripped == last_stmt:
                duplicates += 1
                continue
            result.append(line)
            if stripped and stmt_re.match(line):
                last_stmt = stripped

        return '\n'.join(result), duplicates

    @staticmethod
    def fix_syntax_issues(content: str) -> Tuple[str, int]:
        """Fix common PL/pgSQL syntax issues."""
        fixes = 0
        lines = content.split('\n')
        result = []

        for line in lines:
            # Add missing THEN after IF statements
            if re.match(r'^\s*IF\s+', line, re.IGNORECASE):
                if not re.search(r'THEN\s*$', line, re.IGNORECASE):
                    line = line.rstrip() + ' THEN'
                    fixes += 1

            # Convert SET variable = value to variable := value in PL/pgSQL
            if re.match(r'^\s*SET\s+([vp]_\w+)\s*=', line):
                if not re.search(r'SET\s+(NOCOUNT|XACT_ABORT|IDENTITY_INSERT)', line, re.IGNORECASE):
                    var_match = re.match(r'^(\s*)SET\s+([vp]_\w+)\s*=\s*(.+)', line)
                    if var_match:
                        indent = var_match.group(1)
                        var_name = var_match.group(2)
                        value = var_match.group(3).rstrip(';')
                        line = f'{indent}{var_name} := {value};'
                        fixes += 1

            result.append(line)

        return '\n'.join(result), fixes

    @staticmethod
    def apply_all(content: str) -> EnhancementResult:
        """Apply all Phase 3 enhancements."""
        total_fixes = 0

        # Fix transaction control
        content, fixes = Phase3Enhancements.fix_transaction_control(content)
        total_fixes += fixes

        # Convert error handling
        content, fixes = Phase3Enhancements.convert_error_handling(content)
        total_fixes += fixes

        # Remove duplicates
        content, fixes = Phase3Enhancements.remove_duplicates(content)
        total_fixes += fixes

        # Fix syntax issues
        content, fixes = Phase3Enhancements.fix_syntax_issues(content)
        total_fixes += fixes

        return EnhancementResult(sql=content, fixes_applied=total_fixes)


class EnhancedProceduralConverter:
    """Main converter that applies all phase enhancements."""

    def __init__(self):
        self.phase1 = Phase1Enhancements()
        self.phase2 = Phase2Enhancements()
        self.phase3 = Phase3Enhancements()

    def apply_all_phases(self, content: str) -> EnhancementResult:
        """Apply all Phase 1, 2, 3, and 4 enhancements."""
        all_warnings: List[str] = []
        total_fixes = 0

        # Phase 1: Quick Wins
        result1 = self.phase1.apply_all(content)
        content = result1.sql
        total_fixes += result1.fixes_applied
        if result1.fixes_applied > 0:
            all_warnings.append(f"Phase 1: {result1.fixes_applied} quick win fixes applied")

        # Phase 2: Medium Complexity
        result2 = self.phase2.apply_all(content)
        content = result2.sql
        total_fixes += result2.fixes_applied
        if result2.fixes_applied > 0:
            all_warnings.append(f"Phase 2: {result2.fixes_applied} medium complexity fixes applied")

        # Phase 3: Complex Patterns
        result3 = self.phase3.apply_all(content)
        content = result3.sql
        total_fixes += result3.fixes_applied
        if result3.fixes_applied > 0:
            all_warnings.append(f"Phase 3: {result3.fixes_applied} complex pattern fixes applied")

        # Phase 4: Advanced Patterns (rowcount, cursor, dynamic SQL, errors, dateadd, control flow)
        result4 = Phase4Enhancements.apply_all(content)
        content = result4.sql
        total_fixes += result4.fixes_applied
        all_warnings.extend(result4.warnings)
        if result4.fixes_applied > 0:
            all_warnings.insert(
                len(all_warnings) - len(result4.warnings),
                f"Phase 4: {result4.fixes_applied} advanced pattern fixes applied"
            )

        return EnhancementResult(
            sql=content,
            warnings=all_warnings,
            fixes_applied=total_fixes
        )

    def apply_phase3_and_4(self, content: str) -> EnhancementResult:
        """Apply only Phase 3 and 4 enhancements (when Phase 1-2 are applied separately via AST).

        Used when ASTEnhancer handles Phase 1-2, and this handles Phase 3-4.
        """
        all_warnings: List[str] = []
        total_fixes = 0

        # Phase 3: Complex Patterns
        result3 = self.phase3.apply_all(content)
        content = result3.sql
        total_fixes += result3.fixes_applied
        if result3.fixes_applied > 0:
            all_warnings.append(f"Phase 3: {result3.fixes_applied} complex pattern fixes applied")

        # Phase 4: Advanced Patterns (rowcount, cursor, dynamic SQL, errors, dateadd, control flow)
        result4 = Phase4Enhancements.apply_all(content)
        content = result4.sql
        total_fixes += result4.fixes_applied
        all_warnings.extend(result4.warnings)
        if result4.fixes_applied > 0:
            all_warnings.insert(
                len(all_warnings) - len(result4.warnings),
                f"Phase 4: {result4.fixes_applied} advanced pattern fixes applied"
            )

        return EnhancementResult(
            sql=content,
            warnings=all_warnings,
            fixes_applied=total_fixes
        )
