"""
Module: prepass.py
Purpose: Phase-0 dynamic SQL resolution — inlines EXEC/sp_executesql before the
         main TsqlToPlpgsqlConverter pipeline runs.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from domains.transpilation.dynamic_sql.converter import DynamicSqlProcedureConverter
from domains.transpilation.dynamic_sql.models import ConversionWarning

_DYNAMIC_SQL_PATTERN = re.compile(
    r"\bsp_executesql\b|\bEXEC\s*@\w+|\bEXECUTE\s*@\w+|\bEXEC\s*\(\s*@",
    re.IGNORECASE,
)


@dataclass
class DynamicSqlPrepassResult:
    sql: str
    applied: bool = False
    warnings: list[str] = field(default_factory=list)


def has_resolvable_dynamic_sql(sql: str) -> bool:
    """True when SQL contains EXEC/sp_executesql patterns the resolver handles."""
    return bool(_DYNAMIC_SQL_PATTERN.search(sql))


def apply_dynamic_sql_prepass(sql: str) -> DynamicSqlPrepassResult:
    """Resolve dynamic SQL in a procedure/function body, returning modified T-SQL.

    Does not emit PostgreSQL — the unified pipeline feeds the result to
    ``TsqlToPlpgsqlConverter``.
    """
    if not has_resolvable_dynamic_sql(sql):
        return DynamicSqlPrepassResult(sql=sql, applied=False)

    converter = DynamicSqlProcedureConverter()
    body = converter._extract_body(sql)
    if not body.strip():
        return DynamicSqlPrepassResult(sql=sql, applied=False)

    converter._build_symbol_table(body, sql)
    resolved_body = converter._resolve_dynamic_sql(body)
    if resolved_body.strip() == body.strip():
        return DynamicSqlPrepassResult(sql=sql, applied=False)

    modified = _reinject_procedure_body(sql, resolved_body)
    warnings = _format_warnings(
        converter.resolver.get_warnings()
        + converter.normalizer.get_warnings()
    )
    warnings.insert(
        0,
        "Dynamic SQL pre-pass: inlined EXEC/sp_executesql into static T-SQL before conversion",
    )
    return DynamicSqlPrepassResult(sql=modified, applied=True, warnings=warnings)


def _format_warnings(items: list[ConversionWarning]) -> list[str]:
    return [f"[{w.code}] {w.message}" for w in items]


def _reinject_procedure_body(tsql: str, resolved_body: str) -> str:
    """Replace the inner BEGIN…END body with the resolved static SQL."""
    upper = tsql.upper()
    begin_idx = upper.find("BEGIN")
    if begin_idx < 0:
        return tsql

    body_start = begin_idx + len("BEGIN")
    depth = 0
    end_idx = -1
    for match in re.finditer(r"\b(BEGIN|END)\b", upper[body_start:], re.IGNORECASE):
        token = match.group(1).upper()
        if token == "BEGIN":
            depth += 1
        else:
            if depth == 0:
                end_idx = body_start + match.start()
                break
            depth -= 1

    if end_idx < 0:
        return tsql

    return (
        tsql[:body_start]
        + "\n"
        + resolved_body
        + "\n"
        + tsql[end_idx:]
    )
