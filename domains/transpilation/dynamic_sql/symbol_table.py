"""
Module: symbol_table.py
Purpose: Symbol table for tracking T-SQL variable assignments and building SQL fragments
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import re
from typing import Any

from domains.transpilation.dynamic_sql.models import (
    ConditionalPredicate,
    ConversionWarning,
    FragmentType,
    Severity,
    SqlFragment,
)


class SymbolEntry:
    """Tracks a variable and its accumulated SQL fragments."""

    def __init__(self, name: str, data_type: str | None = None):
        self.name = name
        self.data_type = data_type
        self.fragments: list[SqlFragment] = []
        self.conditional_predicates: list[ConditionalPredicate] = []
        self.is_dynamic_sql = False
        self.current_if_condition: str | None = None

    def add_literal(self, text: str) -> None:
        if not text:
            return
        self.fragments.append(SqlFragment(FragmentType.LITERAL, text))

    def add_variable(self, var_name: str, cast_type: str | None = None) -> None:
        self.fragments.append(
            SqlFragment(FragmentType.VARIABLE, var_name, original_var=var_name)
        )

    def add_expression(self, expr: str) -> None:
        self.fragments.append(SqlFragment(FragmentType.EXPRESSION, expr))

    def get_resolved_sql(self) -> str:
        parts: list[str] = []
        for f in self.fragments:
            if f.ftype == FragmentType.VARIABLE:
                parts.append(f.value)
            else:
                parts.append(f.value)
        return "".join(parts)

    def get_parameterized_vars(self) -> set[str]:
        return {
            f.value
            for f in self.fragments
            if f.ftype == FragmentType.VARIABLE
        }


class SymbolTable:
    """Maps variable names to SymbolEntry objects across scopes."""

    def __init__(self):
        self._scopes: list[dict[str, SymbolEntry]] = [{}]
        self._procedure_params: dict[str, str] = {}
        self._procedure_name: str | None = None
        self._schema_name: str | None = None

    def push_scope(self) -> None:
        self._scopes.append({})

    def pop_scope(self) -> dict[str, SymbolEntry]:
        return self._scopes.pop()

    def declare(self, name: str, data_type: str | None = None) -> SymbolEntry:
        entry = SymbolEntry(name, data_type)
        self._scopes[-1][name.lower()] = entry
        return entry

    def get(self, name: str) -> SymbolEntry | None:
        normalized = name.lower()
        for scope in reversed(self._scopes):
            if normalized in scope:
                return scope[normalized]
        if normalized in self._procedure_params:
            entry = SymbolEntry(name, self._procedure_params[normalized])
            return entry
        return None

    def resolve_sql_variable(
        self, name: str, seen: set[str] | None = None
    ) -> list[SqlFragment]:
        if seen is None:
            seen = set()
        normalized = name.lower()
        if normalized in seen:
            return [SqlFragment(FragmentType.VARIABLE, name)]
        seen.add(normalized)

        entry = self.get(name)
        if entry is None or not entry.fragments:
            return [SqlFragment(FragmentType.VARIABLE, name)]

        resolved: list[SqlFragment] = []
        for f in entry.fragments:
            if f.ftype == FragmentType.VARIABLE:
                resolved.extend(self.resolve_sql_variable(f.value, seen))
            else:
                resolved.append(f)
        return resolved

    def set_procedure_info(
        self, schema: str | None, name: str | None
    ) -> None:
        self._schema_name = schema
        self._procedure_name = name

    def add_procedure_param(self, name: str, data_type: str) -> None:
        self._procedure_params[name.lower()] = data_type

    @property
    def procedure_name(self) -> str | None:
        return self._procedure_name

    @property
    def schema_name(self) -> str | None:
        return self._schema_name
