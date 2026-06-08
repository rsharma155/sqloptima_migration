"""
Module: domains/transpilation/converters/dynamic_sql_converter.py
Purpose: Converts T-SQL EXEC and sp_executesql patterns to PL/pgSQL EXECUTE USING.
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
    """Result of applying dynamic SQL enhancements."""

    sql: str
    warnings: List[str] = field(default_factory=list)
    fixes_applied: int = 0


class DynamicSqlConverter:
    """Handles T-SQL EXEC sp_executesql and EXEC @var conversion.

    Converts:
    - EXEC sp_executesql @sql, N'@Param1 TYPE, ...', @Param1, ... → EXECUTE v_sql USING v_Param1, ...;
    - EXEC (@sql) → EXECUTE v_sql;
    - EXEC dbo.proc_name @param → PERFORM proc_name(p_param);
    """

    _SP_EXECUTESQL_PATTERN = re.compile(
        r"(?:^|\s)(?:EXEC(?:UTE)?)\s+(?:(?:\[\w+\]\.)?(?:\[sp_executesql\]|sp_executesql))\s+"
        r"(@\w+)(?:\s*,\s*N?['\"]([^'\"]*?)['\"])?(?:\s*,\s*(.+?))?(?=\s*;)",
        re.IGNORECASE | re.DOTALL | re.MULTILINE,
    )

    _EXEC_VAR_PATTERN = re.compile(
        r'EXEC\s*\(\s*(@\w+)\s*\)\s*;',
        re.IGNORECASE,
    )

    _EXEC_STATIC_PATTERN = re.compile(
        r'EXEC\s+(?:\[?(?:\w+\.)?(\w+)\]?)(?:\s+(.+?))?;',
        re.IGNORECASE,
    )

    @staticmethod
    def _convert_var_prefix(var: str) -> str:
        """Convert @VarName to v_VarName."""
        if var.startswith('@'):
            return f'v_{var[1:]}'
        return var

    @staticmethod
    def convert_sp_executesql(content: str) -> Tuple[str, int]:
        """Convert EXEC sp_executesql patterns to EXECUTE USING.

        Args:
            content: SQL content to process

        Returns:
            Tuple of (modified_sql, count_of_conversions)
        """
        if 'SP_EXECUTESQL' not in content.upper():
            return content, 0

        count = 0

        def replace_sp_executesql(m: re.Match) -> str:
            nonlocal count
            count += 1
            sql_var = m.group(1)  # @sql variable
            param_decl = m.group(2)  # N'@Param1 INT, ...' declaration
            param_values = m.group(3)  # Actual parameter values

            converted_sql_var = DynamicSqlConverter._convert_var_prefix(sql_var)

            if param_values:
                param_text = param_values.strip()
                named = re.findall(r"@\w+\s*=\s*([^,;]+)", param_text)
                if named:
                    converted_params = ", ".join(
                        DynamicSqlConverter._convert_var_prefix(v.strip())
                        if v.strip().startswith("@")
                        else v.strip()
                        for v in named
                    )
                else:
                    param_list = [p.strip() for p in re.split(r",", param_text) if p.strip()]
                    converted_params = ", ".join(
                        DynamicSqlConverter._convert_var_prefix(p) for p in param_list if p.strip()
                    )
                return f"EXECUTE {converted_sql_var} USING {converted_params};"
            else:
                return f'EXECUTE {converted_sql_var};'

        converted = DynamicSqlConverter._SP_EXECUTESQL_PATTERN.sub(replace_sp_executesql, content)
        return converted, count

    @staticmethod
    def convert_exec_variable(content: str) -> Tuple[str, int]:
        """Convert EXEC (@sql) dynamic execution.

        Args:
            content: SQL content to process

        Returns:
            Tuple of (modified_sql, count_of_conversions)
        """
        if 'EXEC' not in content.upper():
            return content, 0

        matches = list(DynamicSqlConverter._EXEC_VAR_PATTERN.finditer(content))

        def replace_exec_var(m: re.Match) -> str:
            sql_var = m.group(1)
            converted_var = DynamicSqlConverter._convert_var_prefix(sql_var)
            return f'EXECUTE {converted_var};'

        converted = DynamicSqlConverter._EXEC_VAR_PATTERN.sub(replace_exec_var, content)
        count = len(matches)
        return converted, count

    @staticmethod
    def convert_static_exec(content: str) -> Tuple[str, int]:
        """Convert EXEC proc_name @param to PERFORM/CALL pattern.

        Args:
            content: SQL content to process

        Returns:
            Tuple of (modified_sql, count_of_conversions)
        """
        if 'EXEC' not in content.upper():
            return content, 0

        # Simple heuristic: find EXEC with a procedure name (not sp_executesql, not @var)
        # Replace with PERFORM proc_name(params);
        pattern = re.compile(
            r'EXEC\s+(?:dbo\.)?(\w+)(?:\s+(@\w+(?:\s*,\s*@\w+)*))?;',
            re.IGNORECASE,
        )

        matches = list(pattern.finditer(content))

        def replace_exec_static(m: re.Match) -> str:
            proc_name = m.group(1)
            params = m.group(2)

            if params:
                param_list = [p.strip() for p in params.split(',')]
                converted_params = ', '.join(
                    DynamicSqlConverter._convert_var_prefix(p) for p in param_list
                )
                return f'PERFORM {proc_name}({converted_params});'
            else:
                return f'PERFORM {proc_name}();'

        converted = pattern.sub(replace_exec_static, content)
        count = len(matches)
        return converted, count

    @staticmethod
    def apply_all(content: str) -> EnhancementResult:
        """Apply all dynamic SQL conversion steps.

        Order:
        1. Convert sp_executesql patterns
        2. Convert EXEC @var patterns
        3. Convert static EXEC patterns

        Args:
            content: SQL content to process

        Returns:
            EnhancementResult with modified SQL and stats
        """
        if 'EXEC' not in content.upper():
            return EnhancementResult(sql=content, warnings=[], fixes_applied=0)

        warnings = []
        total_fixes = 0

        sql, count = DynamicSqlConverter.convert_sp_executesql(content)
        total_fixes += count

        sql, count = DynamicSqlConverter.convert_exec_variable(sql)
        total_fixes += count

        sql, count = DynamicSqlConverter.convert_static_exec(sql)
        total_fixes += count

        if total_fixes > 0:
            warnings.append(
                f'T-SQL EXEC patterns converted to PL/pgSQL EXECUTE/PERFORM ({total_fixes} changes). '
                'Review for correct parameter types and dynamic SQL safety.'
            )

        return EnhancementResult(sql=sql, warnings=warnings, fixes_applied=total_fixes)
