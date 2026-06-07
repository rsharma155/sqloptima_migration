"""
Module: domains/transpilation/ast_enhancements.py
Purpose: AST-based Phase 1 and Phase 2 enhancements for T-SQL → PL/pgSQL conversion.

Phase 1: Parameter and variable fixes (AST-based)
- Variable prefix mapping (@var → p_var for params, v_var for locals)
- SCOPE_IDENTITY() → LASTVAL() function replacement

Phase 2: Hint and pattern cleanup (AST-based)
- Remove T-SQL WITH hints (NOLOCK, ROWLOCK, XLOCK, INDEX, etc.)
- Remove OPTION hints (MAXDOP, RECOMPILE, etc.)
- Flag complex patterns for manual review

Author: Claude Code (Haiku 4.5)
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Set

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.qualify import qualify


@dataclass
class ASTEnhancementResult:
    """Result of applying AST-based enhancements."""

    sql: str
    warnings: List[str] = field(default_factory=list)
    fixes_applied: int = 0


class Phase1ASTEnhancements:
    """Phase 1: Variable and function mapping via AST visitors."""

    @staticmethod
    def replace_scope_identity(parsed: exp.Expression) -> tuple[exp.Expression, int]:
        """Replace SCOPE_IDENTITY() with LASTVAL() at AST level.

        Args:
            parsed: SQLGlot parsed AST

        Returns:
            Tuple of (modified_ast, count_of_replacements)
        """
        count = 0

        def replace_scope_identity_func(node: exp.Expression) -> exp.Expression:
            nonlocal count
            if isinstance(node, exp.Anonymous) and node.name.upper() == "SCOPE_IDENTITY":
                count += 1
                return exp.Anonymous(this="LASTVAL")
            return node

        transformed = parsed.transform(replace_scope_identity_func)
        return transformed, count

    @staticmethod
    def replace_variable_prefixes(
        parsed: exp.Expression, param_names: Set[str] | None = None
    ) -> tuple[exp.Expression, int]:
        """Prefix T-SQL variables with p_ (params) or v_ (locals).

        T-SQL uses @param_name syntax. PL/pgSQL uses plain identifiers.
        This maps:
        - @param_name (in parameter list) → p_param_name
        - @var_name (in body) → v_var_name

        Args:
            parsed: SQLGlot parsed AST
            param_names: Set of parameter names to distinguish from locals

        Returns:
            Tuple of (modified_ast, count_of_replacements)
        """
        if param_names is None:
            param_names = set()

        count = 0

        def replace_var(node: exp.Expression) -> exp.Expression:
            nonlocal count
            # Look for identifiers starting with @ (T-SQL variable syntax)
            if isinstance(node, exp.Identifier):
                name = node.name
                if name.startswith("@"):
                    # Strip @ and add appropriate prefix
                    clean_name = name[1:]
                    if clean_name in param_names:
                        node.name = f"p_{clean_name}"
                    else:
                        node.name = f"v_{clean_name}"
                    count += 1
            return node

        transformed = parsed.transform(replace_var)
        return transformed, count

    @staticmethod
    def apply_all(sql: str) -> ASTEnhancementResult:
        """Apply all Phase 1 AST enhancements.

        Args:
            sql: T-SQL or transpiled SQL source

        Returns:
            ASTEnhancementResult with modified SQL and stats
        """
        try:
            parsed = sqlglot.parse_one(sql, dialect="tsql")
        except Exception as e:
            return ASTEnhancementResult(sql=sql, warnings=[f"Parse error: {e}"], fixes_applied=0)

        total_fixes = 0
        warnings = []

        # Replace SCOPE_IDENTITY with LASTVAL (may still appear if SQLGlot missed it)
        parsed, scope_count = Phase1ASTEnhancements.replace_scope_identity(parsed)
        total_fixes += scope_count
        if scope_count > 0:
            warnings.append(f"Replaced {scope_count} SCOPE_IDENTITY() calls with LASTVAL()")

        # Replace variable prefixes (@var → v_var) for any residual T-SQL variables
        parsed, var_count = Phase1ASTEnhancements.replace_variable_prefixes(parsed)
        total_fixes += var_count
        if var_count > 0:
            warnings.append(f"Prefixed {var_count} T-SQL variables")

        # Convert back to SQL
        result_sql = parsed.sql(dialect="postgres")

        return ASTEnhancementResult(sql=result_sql, warnings=warnings, fixes_applied=total_fixes)


class Phase2ASTEnhancements:
    """Phase 2: Remove hints and flag complex patterns via AST."""

    @staticmethod
    def remove_table_hints(parsed: exp.Expression) -> tuple[exp.Expression, int]:
        """Remove T-SQL WITH hints from table references (NOLOCK, ROWLOCK, XLOCK, INDEX, etc.).

        In T-SQL, hints are written as: table_name WITH (NOLOCK, ROWLOCK, ...)
        PostgreSQL doesn't support these, so we remove them.

        Args:
            parsed: SQLGlot parsed AST

        Returns:
            Tuple of (modified_ast, count_of_removals)
        """
        count = 0

        def remove_hints(node: exp.Expression) -> exp.Expression:
            nonlocal count
            if isinstance(node, exp.Table):
                # SQLGlot stores hints as a list in the 'hints' attribute
                if hasattr(node, 'hints') and node.hints:
                    count += len(node.hints)
                    node.args['hints'] = []
            return node

        transformed = parsed.transform(remove_hints)
        return transformed, count

    @staticmethod
    def remove_option_hints(parsed: exp.Expression) -> tuple[exp.Expression, int]:
        """Remove OPTION hints from SELECT statements (MAXDOP, RECOMPILE, etc.).

        In T-SQL, query hints appear as: SELECT ... OPTION (MAXDOP, RECOMPILE, ...)
        PostgreSQL uses different syntax, so we remove them for now.

        Args:
            parsed: SQLGlot parsed AST

        Returns:
            Tuple of (modified_ast, count_of_removals)
        """
        count = 0

        def remove_options(node: exp.Expression) -> exp.Expression:
            nonlocal count
            if isinstance(node, exp.Select) and hasattr(node, "args") and "sql" in node.args:
                # SQLGlot may store hints differently depending on version
                # For now, we iterate and remove if found
                if "hint" in node.args:
                    count += 1
                    node.args.pop("hint", None)
            return node

        transformed = parsed.transform(remove_options)
        return transformed, count

    @staticmethod
    def flag_complex_patterns(sql: str) -> tuple[str, int]:
        """Flag complex patterns that require manual review (still uses simple regex for detection).

        Patterns flagged:
        - MERGE statements (need INSERT ON CONFLICT)
        - CURSOR operations (need REFCURSOR)
        - Dynamic SQL (sp_executesql, EXEC)

        Args:
            sql: Source SQL

        Returns:
            Tuple of (modified_sql, count_of_flags)
        """
        import re

        flags_added = 0
        result = sql

        # Flag MERGE
        if re.search(r"\bMERGE\s+", sql, re.IGNORECASE):
            if "-- PHASE2: MERGE" not in result:
                result = re.sub(
                    r"(\bMERGE\s+)",
                    r"-- PHASE2: MERGE not natively supported in PostgreSQL; convert to INSERT ON CONFLICT\n    \1",
                    result,
                    flags=re.IGNORECASE,
                    count=1,
                )
                flags_added += 1

        # Flag CURSOR operations
        if re.search(r"\bCURSOR\s+", sql, re.IGNORECASE) and re.search(r"\bREFCURSOR", sql, re.IGNORECASE):
            if "-- PHASE2: REFCURSOR" not in result:
                result = re.sub(
                    r"(\bCURSOR\s+)",
                    r"-- PHASE2: REFCURSOR requires manual conversion\n    \1",
                    result,
                    flags=re.IGNORECASE,
                    count=1,
                )
                flags_added += 1

        # Flag sp_executesql (dynamic SQL)
        if re.search(r"\bsp_executesql\b", sql, re.IGNORECASE):
            if "-- PHASE2: sp_executesql" not in result:
                result = re.sub(
                    r"(\bsp_executesql\b)",
                    r"-- PHASE2: Dynamic SQL (sp_executesql) needs EXECUTE USING conversion\n    \1",
                    result,
                    flags=re.IGNORECASE,
                    count=1,
                )
                flags_added += 1

        return result, flags_added

    @staticmethod
    def apply_all(sql: str) -> ASTEnhancementResult:
        """Apply all Phase 2 AST enhancements.

        Args:
            sql: T-SQL or transpiled SQL source

        Returns:
            ASTEnhancementResult with modified SQL and stats
        """
        try:
            parsed = sqlglot.parse_one(sql, dialect="tsql")
        except Exception as e:
            return ASTEnhancementResult(sql=sql, warnings=[f"Parse error: {e}"], fixes_applied=0)

        total_fixes = 0
        warnings = []

        # Remove table hints
        parsed, hint_count = Phase2ASTEnhancements.remove_table_hints(parsed)
        total_fixes += hint_count
        if hint_count > 0:
            warnings.append(f"Removed {hint_count} table hint(s)")

        # Remove option hints
        parsed, option_count = Phase2ASTEnhancements.remove_option_hints(parsed)
        total_fixes += option_count
        if option_count > 0:
            warnings.append(f"Removed {option_count} option hint(s)")

        # Convert back to SQL
        result_sql = parsed.sql(dialect="postgres")

        # Flag complex patterns (still uses regex for now as AST detection is complex)
        result_sql, flags = Phase2ASTEnhancements.flag_complex_patterns(result_sql)
        total_fixes += flags
        if flags > 0:
            warnings.append(f"Flagged {flags} complex pattern(s) for review")

        return ASTEnhancementResult(sql=result_sql, warnings=warnings, fixes_applied=total_fixes)


class ASTEnhancer:
    """Orchestrates Phase 1 and Phase 2 AST-based enhancements."""

    @staticmethod
    def enhance(sql: str, apply_phase1: bool = True, apply_phase2: bool = True) -> ASTEnhancementResult:
        """Apply AST-based enhancements in sequence.

        Expects plain SQL (not dollar-quoted PL/pgSQL); apply before wrapping.
        """
        current_sql = sql
        all_warnings: list[str] = []
        total_fixes = 0

        if apply_phase1:
            result = Phase1ASTEnhancements.apply_all(current_sql)
            current_sql = result.sql
            all_warnings.extend(result.warnings)
            total_fixes += result.fixes_applied

        if apply_phase2:
            result = Phase2ASTEnhancements.apply_all(current_sql)
            current_sql = result.sql
            all_warnings.extend(result.warnings)
            total_fixes += result.fixes_applied

        return ASTEnhancementResult(sql=current_sql, warnings=all_warnings, fixes_applied=total_fixes)
