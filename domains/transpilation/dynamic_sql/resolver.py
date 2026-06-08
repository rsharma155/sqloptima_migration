"""
Module: resolver.py
Purpose: Dynamic SQL resolver — detects EXEC()/EXECUTE()/sp_executesql
         calls, tracks variable concatenation, and produces normalized static SQL.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import re
from typing import Any

import sqlglot
import sqlglot.expressions as exp
from sqlglot import parse_one

from domains.transpilation.dynamic_sql.models import (
    ConditionalPredicate,
    ConversionWarning,
    DynamicSqlStatement,
    FragmentType,
    Severity,
    SqlFragment,
)
from domains.transpilation.dynamic_sql.symbol_table import SymbolEntry, SymbolTable

_EXEC_PATTERN = re.compile(
    r"(EXECUTE\s*|EXEC\s*|sp_executesql)\s*",
    re.IGNORECASE,
)

_SP_EXECUTESQL_PARAM_PATTERN = re.compile(
    r"sp_executesql\s+(N?'.*?'|@\w+)\s*,\s*(N?'.*?'|@\w+)\s*,\s*(.*)",
    re.IGNORECASE | re.DOTALL,
)

_VARIABLE_REF = re.compile(r"@\w+")


class DynamicSqlResolver:
    """Resolves dynamic SQL statements by tracking variable assignments
    and normalizing EXEC/sp_executesql calls into static SQL."""

    def __init__(self, symbol_table: SymbolTable):
        self.symbol_table = symbol_table
        self.warnings: list[ConversionWarning] = []

    def resolve_statement(self, sql: str) -> DynamicSqlStatement:
        """Parse a single SQL statement and resolve dynamic SQL if present."""
        stmt = DynamicSqlStatement()

        exec_match = _EXEC_PATTERN.match(sql.strip())
        if not exec_match:
            stmt.normalized_sql = sql
            return stmt

        exec_type = exec_match.group(1).strip().lower()
        remaining = sql[exec_match.end():].strip()

        if exec_type == "sp_executesql":
            stmt.uses_sp_executesql = True
            return self._resolve_sp_executesql(remaining, stmt)
        else:
            return self._resolve_exec(remaining, stmt)

    def _resolve_exec(
        self, arg: str, stmt: DynamicSqlStatement
    ) -> DynamicSqlStatement:
        arg = arg.rstrip(";")
        if arg.startswith("(") and arg.endswith(")"):
            arg = arg[1:-1]

        arg = arg.strip()
        if arg.startswith("'") and arg.endswith("'"):
            arg = arg[1:-1]
            stmt.fragments = [SqlFragment(FragmentType.LITERAL, arg)]
            stmt.normalized_sql = arg
            return stmt

        if arg.upper().startswith("N'") and arg.endswith("'"):
            arg = arg[2:-1]
            stmt.fragments = [SqlFragment(FragmentType.LITERAL, arg)]
            stmt.normalized_sql = arg
            return stmt

        var_match = re.match(r"^@(\w+)", arg)
        if var_match:
            var_name = "@" + var_match.group(1)
            resolved = self.symbol_table.resolve_sql_variable(var_name)
            stmt.fragments = resolved
            stmt.normalized_sql = self._fragments_to_sql(resolved)
            return stmt

        stmt.fragments = [SqlFragment(FragmentType.LITERAL, arg)]
        stmt.normalized_sql = arg
        return stmt

    def _resolve_sp_executesql(
        self, arg: str, stmt: DynamicSqlStatement
    ) -> DynamicSqlStatement:
        parts = self._split_sp_executesql_args(arg)
        if not parts:
            stmt.normalized_sql = arg
            return stmt

        sql_arg = parts[0]
        params_decl = parts[1] if len(parts) > 1 else ""
        param_assignments = parts[2] if len(parts) > 2 else ""

        if sql_arg.startswith("'") or sql_arg.startswith("N'"):
            raw_sql = sql_arg.strip()
            if raw_sql.upper().startswith("N'"):
                raw_sql = raw_sql[1:]
            if raw_sql.startswith("'") and raw_sql.endswith("'"):
                raw_sql = raw_sql[1:-1]
            stmt.fragments = [SqlFragment(FragmentType.LITERAL, raw_sql)]
            stmt.normalized_sql = raw_sql
        else:
            var_match = re.match(r"^@(\w+)", sql_arg)
            if var_match:
                var_name = "@" + var_match.group(1)
                resolved = self.symbol_table.resolve_sql_variable(var_name)
                stmt.fragments = resolved
                stmt.normalized_sql = self._fragments_to_sql(resolved)

        if params_decl and param_assignments:
            stmt.params = self._parse_sp_executesql_params(
                params_decl, param_assignments
            )

        return stmt

    def _split_sp_executesql_args(self, arg: str) -> list[str]:
        """Naively split sp_executesql arguments by comma respecting string literals."""
        parts = []
        depth = 0
        in_string = False
        string_char = None
        current: list[str] = []

        i = 0
        while i < len(arg):
            ch = arg[i]
            if in_string:
                current.append(ch)
                if ch == string_char and (i == 0 or arg[i - 1] != "\\"):
                    in_string = False
                    string_char = None
            elif ch in ("'", '"'):
                in_string = True
                string_char = ch
                current.append(ch)
            elif ch in ("N", "n") and i + 1 < len(arg) and arg[i + 1] == "'":
                current.append(ch)
            elif ch == "," and depth == 0:
                parts.append("".join(current).strip())
                current = []
            else:
                current.append(ch)
            i += 1

        if current:
            rest = "".join(current).strip()
            if rest:
                parts.append(rest)

        return parts[:3]

    def _parse_sp_executesql_params(
        self, params_decl: str, param_assignments: str
    ) -> dict[str, str]:
        params: dict[str, str] = {}
        decls = [p.strip() for p in params_decl.split(",") if p.strip()]
        assignments = [
            a.strip() for a in param_assignments.split(",") if a.strip()
        ]

        type_map: dict[str, str] = {}
        for d in decls:
            m = re.match(r"@(\w+)\s+(.+?)(?:\s*=\s*.+)?$", d, re.IGNORECASE)
            if m:
                type_map["@" + m.group(1)] = m.group(2).strip()

        for a in assignments:
            m = re.match(r"@(\w+)\s*=\s*(.+)", a, re.IGNORECASE)
            if m:
                var_name = "@" + m.group(1)
                value = m.group(2).strip()
                params[var_name] = value
            else:
                m2 = re.match(r"@(\w+)\s+(.+)", a, re.IGNORECASE)
                if m2:
                    var_name = "@" + m2.group(1)
                    params[var_name] = type_map.get(var_name, "")

        return params

    def _fragments_to_sql(self, fragments: list[SqlFragment]) -> str:
        parts: list[str] = []
        for f in fragments:
            if f.ftype == FragmentType.VARIABLE:
                parts.append(f.value)
            else:
                parts.append(f.value)
        return "".join(parts)

    def get_warnings(self) -> list[ConversionWarning]:
        return self.warnings
