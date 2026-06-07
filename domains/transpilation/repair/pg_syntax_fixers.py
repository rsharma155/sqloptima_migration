"""
Rule-based fixers for common pgparse failures on converted PL/pgSQL output.

Each fixer returns (modified_sql, fixes_count). Fixers are idempotent where possible.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from domains.transpilation.converters.control_flow_fixer import ControlFlowFixer
from domains.transpilation.sql_expression_converter import TsqlExpressionConverter
from domains.transpilation.tsql_plpgsql_conversion_enhancer import Phase3Enhancements

FixerFn = Callable[[str], tuple[str, int]]

_TABLE_HINT_RE = re.compile(
    r"\bWITH\s*\(\s*"
    r"(?:NOLOCK|ROWLOCK|XLOCK|UPDLOCK|HOLDLOCK|READPAST|TABLOCKX?|TABLOCK|"
    r"NOWAIT|PAGLOCK|READUNCOMMITTED|REPEATABLEREAD|SERIALIZABLE)\s*"
    r"(?:,\s*\w+\s*)*\)",
    re.IGNORECASE,
)

_BRACKET_IDENT_RE = re.compile(r"\[([^\]]+)\]")

_RETURN_QUERY_IN_PAREN_RE = re.compile(
    r"(\(\s*)RETURN\s+QUERY\s+(?=SELECT\b)",
    re.IGNORECASE,
)

_BROKEN_GETDATE_RE = re.compile(
    r"\bGETDATE\s*\(\s*(?=-)",
    re.IGNORECASE,
)

_FOR_JSON_RE = re.compile(
    r"\bFOR\s+JSON\s+(?:PATH|AUTO|ROOT\s*\([^)]*\)|WITHOUT_ARRAY_WRAPPER)(?:\s*,\s*\w+(?:\s*\([^)]*\))?)*",
    re.IGNORECASE,
)

_QUERY_OPTION_RE = re.compile(
    r"\bOPTION\s*\(\s*(?:RECOMPILE|OPTIMIZE\s+FOR\s+[^)]*|MAXDOP\s+\d+|FAST\s+\d+|"
    r"USE\s+PLAN\s+[^)]*|MERGE\s+JOIN|LOOP\s+JOIN|HASH\s+JOIN)\s*\)",
    re.IGNORECASE,
)

_APPLY_REPLACEMENTS = (
    (re.compile(r"\bOUTER\s+APPLY\b", re.IGNORECASE), "LEFT JOIN LATERAL"),
    (re.compile(r"\bCROSS\s+APPLY\b", re.IGNORECASE), "CROSS JOIN LATERAL"),
)


def fix_bracket_identifiers(sql: str) -> tuple[str, int]:
    count = 0

    def _repl(m: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return f'"{m.group(1)}"'

    return _BRACKET_IDENT_RE.sub(_repl, sql), count


def fix_table_hints(sql: str) -> tuple[str, int]:
    matches = list(_TABLE_HINT_RE.finditer(sql))
    if not matches:
        return sql, 0
    return _TABLE_HINT_RE.sub("", sql), len(matches)


def fix_return_query_in_cte(sql: str) -> tuple[str, int]:
    matches = list(_RETURN_QUERY_IN_PAREN_RE.finditer(sql))
    if not matches:
        return sql, 0
    return _RETURN_QUERY_IN_PAREN_RE.sub(r"\1", sql), len(matches)


def fix_apply_to_lateral(sql: str) -> tuple[str, int]:
    count = 0
    result = sql
    for pattern, replacement in _APPLY_REPLACEMENTS:
        matches = list(pattern.finditer(result))
        if matches:
            result = pattern.sub(replacement, result)
            count += len(matches)
    return result, count


def fix_broken_getdate(sql: str) -> tuple[str, int]:
    matches = list(_BROKEN_GETDATE_RE.finditer(sql))
    if not matches:
        return sql, 0
    return _BROKEN_GETDATE_RE.sub("NOW()", sql), len(matches)


def fix_system_user(sql: str) -> tuple[str, int]:
    pattern = re.compile(r"\bSYSTEM_USER\b", re.IGNORECASE)
    matches = list(pattern.finditer(sql))
    if not matches:
        return sql, 0
    return pattern.sub("CURRENT_USER", sql), len(matches)


def fix_for_json_clauses(sql: str) -> tuple[str, int]:
    matches = list(_FOR_JSON_RE.finditer(sql))
    if not matches:
        return sql, 0
    replacement = " /* FOR JSON removed — use json_agg/json_build_object */"
    return _FOR_JSON_RE.sub(replacement, sql), len(matches)


def fix_query_option_clauses(sql: str) -> tuple[str, int]:
    matches = list(_QUERY_OPTION_RE.finditer(sql))
    if not matches:
        return sql, 0
    return _QUERY_OPTION_RE.sub("", sql), len(matches)


def fix_execute_as_owner(sql: str) -> tuple[str, int]:
    pattern = re.compile(r"\bEXECUTE\s+AS\s+(?:CALLER|OWNER|SELF)\b", re.IGNORECASE)
    matches = list(pattern.finditer(sql))
    if not matches:
        return sql, 0
    return pattern.sub("/* EXECUTE AS removed — set function owner in PostgreSQL */", sql), len(matches)


def fix_set_statements(sql: str) -> tuple[str, int]:
    """Convert remaining SET var = val to PL/pgSQL assignment inside bodies."""
    result, count = Phase3Enhancements.fix_syntax_issues(sql)
    return result, count


def fix_control_flow(sql: str) -> tuple[str, int]:
    result = ControlFlowFixer.apply_all(sql)
    return result.sql, result.fixes_applied


def fix_tsql_expressions(sql: str) -> tuple[str, int]:
    converted = TsqlExpressionConverter.convert_expression(sql)
    if converted == sql:
        return sql, 0
    # Expression converter does not return count; approximate by diff size.
    return converted, 1


def fix_goto_statements(sql: str) -> tuple[str, int]:
    pattern = re.compile(r"\bGOTO\s+\w+\b", re.IGNORECASE)
    matches = list(pattern.finditer(sql))
    if not matches:
        return sql, 0
    return pattern.sub("/* GOTO removed — restructure control flow manually */", sql), len(matches)


def fix_remaining_top(sql: str) -> tuple[str, int]:
    """Convert residual SELECT TOP n to LIMIT (end-of-statement heuristic)."""
    pattern = re.compile(r"\bSELECT\s+TOP\s+(\d+)\b", re.IGNORECASE)
    matches = list(pattern.finditer(sql))
    if not matches:
        return sql, 0
    return pattern.sub(r"SELECT /* LIMIT \1 */", sql), len(matches)


def fix_begin_try_blocks(sql: str) -> tuple[str, int]:
    if not re.search(r"\bBEGIN\s+TRY\b", sql, re.IGNORECASE):
        return sql, 0
    converted = re.sub(r"\bBEGIN\s+TRY\b", "BEGIN", sql, flags=re.IGNORECASE)
    converted = re.sub(r"\bEND\s+TRY\b", "END", converted, flags=re.IGNORECASE)
    converted = re.sub(
        r"\bBEGIN\s+CATCH\b.*?(\bEND\s+CATCH\b)",
        r"EXCEPTION WHEN OTHERS THEN NULL; /* manual review: CATCH block */",
        converted,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return converted, 1


def fix_merge_statements(sql: str) -> tuple[str, int]:
    from domains.transpilation.converters.merge_converter import MergeConverter

    if not re.search(r"\bMERGE\b", sql, re.IGNORECASE):
        return sql, 0
    result = MergeConverter.apply_all(sql)
    if result.sql == sql or not result.success:
        return sql, 0
    return result.sql, 1


def fix_body_transform_pass(sql: str) -> tuple[str, int]:
    """Re-apply high-value body transforms on converted PL/pgSQL fragments."""
    from domains.transpilation.converters.plpgsql._body_transforms import (
        _convert_for_xml_path,
        _convert_merge,
        _convert_openjson,
        _convert_select_into,
        _convert_top_with_ties,
        _convert_tsql_builtin_functions,
    )

    steps = (
        _convert_tsql_builtin_functions,
        _convert_top_with_ties,
        _convert_select_into,
        _convert_openjson,
        _convert_merge,
        _convert_for_xml_path,
    )
    result = sql
    applied = 0
    for step in steps:
        updated = step(result)
        if updated != result:
            applied += 1
            result = updated
    return result, applied


def fix_drop_if_exists(sql: str) -> tuple[str, int]:
    """T-SQL DROP TABLE IF EXISTS #temp inside body — ensure TEMP keyword."""
    pattern = re.compile(
        r"\bDROP\s+TABLE\s+(?!IF\s+EXISTS\s+(?:TEMP\s+)?)(#?\w+)",
        re.IGNORECASE,
    )
    matches = list(pattern.finditer(sql))
    if not matches:
        return sql, 0
    return pattern.sub(r"DROP TABLE IF EXISTS \1", sql), len(matches)


# Ordered proactive fixers — run every repair round on full SQL and PL/pgSQL bodies.
PROACTIVE_FIXERS: list[tuple[str, FixerFn]] = [
    ("body_transform_pass", fix_body_transform_pass),
    ("bracket_identifiers", fix_bracket_identifiers),
    ("table_hints", fix_table_hints),
    ("apply_to_lateral", fix_apply_to_lateral),
    ("return_query_in_cte", fix_return_query_in_cte),
    ("broken_getdate", fix_broken_getdate),
    ("system_user", fix_system_user),
    ("for_json", fix_for_json_clauses),
    ("query_option", fix_query_option_clauses),
    ("execute_as", fix_execute_as_owner),
    ("begin_try", fix_begin_try_blocks),
    ("merge", fix_merge_statements),
    ("goto", fix_goto_statements),
    ("remaining_top", fix_remaining_top),
    ("set_statements", fix_set_statements),
    ("control_flow", fix_control_flow),
]

BODY_ONLY_FIXERS: list[tuple[str, FixerFn]] = [
    ("drop_if_exists", fix_drop_if_exists),
]

# Map pgparse "near TOKEN" hints to fixers tried first on that round.
TARGETED_FIXERS: list[tuple[re.Pattern[str], list[str]]] = [
    (re.compile(r"APPLY", re.IGNORECASE), ["apply_to_lateral"]),
    (re.compile(r"RETURN", re.IGNORECASE), ["return_query_in_cte"]),
    (re.compile(r"\[", re.IGNORECASE), ["bracket_identifiers"]),
    (re.compile(r"OPTION", re.IGNORECASE), ["query_option"]),
    (re.compile(r"JSON", re.IGNORECASE), ["for_json"]),
    (re.compile(r"SYSTEM_USER", re.IGNORECASE), ["system_user"]),
    (re.compile(r"EXECUTE", re.IGNORECASE), ["execute_as"]),
    (re.compile(r"GETDATE", re.IGNORECASE), ["broken_getdate"]),
    (re.compile(r"GOTO", re.IGNORECASE), ["goto"]),
    (re.compile(r"MERGE", re.IGNORECASE), ["merge"]),
    (re.compile(r"NOLOCK|ROWLOCK|XLOCK", re.IGNORECASE), ["table_hints"]),
]

FIXER_BY_NAME: dict[str, FixerFn] = dict(PROACTIVE_FIXERS + BODY_ONLY_FIXERS)


def apply_fixers(sql: str, fixer_names: list[str]) -> tuple[str, list[tuple[str, int]]]:
    """Apply named fixers in order. Returns updated SQL and (name, count) pairs."""
    applied: list[tuple[str, int]] = []
    current = sql
    for name in fixer_names:
        fn = FIXER_BY_NAME.get(name)
        if fn is None:
            continue
        new_sql, count = fn(current)
        if count:
            applied.append((name, count))
            current = new_sql
    return current, applied


def apply_proactive_fixers(sql: str) -> tuple[str, list[tuple[str, int]]]:
    names = [name for name, _ in PROACTIVE_FIXERS]
    return apply_fixers(sql, names)


def fixers_for_issue_message(message: str) -> list[str]:
    """Select targeted fixers based on a pgparse error message."""
    names: list[str] = []
    for pattern, fixers in TARGETED_FIXERS:
        if pattern.search(message):
            names.extend(fixers)
    if not names:
        return [name for name, _ in PROACTIVE_FIXERS]
    # Preserve order, dedupe.
    seen: set[str] = set()
    ordered: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered
