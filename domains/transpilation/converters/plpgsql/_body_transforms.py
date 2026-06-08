"""
Module: domains/transpilation/converters/plpgsql/_body_transforms.py
Purpose: All T-SQL → PL/pgSQL body transformation functions and the
         TsqlBodyConverter orchestrator class.

         This module applies ~25 transformation passes to the raw T-SQL body,
         converting SQL Server idioms to their PostgreSQL equivalents.  The
         ordering of passes is significant — see TsqlBodyConverter.convert()
         for the full pipeline.

Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import re
from typing import Optional

from domains.transpilation.converters.plpgsql._models import ParamInfo
from domains.transpilation.converters.plpgsql._type_mapper import TsqlTypeMapper


# ---------------------------------------------------------------------------
# TsqlBodyConverter
# ---------------------------------------------------------------------------

class TsqlBodyConverter:
    """Converts a T-SQL procedure/function body to PL/pgSQL."""

    @staticmethod
    def convert(body: str, params: list[ParamInfo]) -> str:
        """Apply all body transformation rules and return PL/pgSQL body."""
        result = body
        param_names = {p.name.upper() for p in params}

        # Apply transformations in order (ordering matters for some rules)
        result = _expand_multi_var_declare(result)  # must be before variable_references
        result = _remove_session_settings(result)
        result = _strip_n_prefix(result)
        result = _convert_for_xml_path(result)  # before string concat (+ → ||)
        result = _convert_try_catch(result)
        result = _convert_print(result)
        result = _convert_raiserror(result)
        result = _convert_year_month_day(result)
        result = _convert_tsql_builtin_functions(result)
        result = _convert_convert_function(result)
        result = _convert_iif(result)
        result = _convert_choose(result)
        result = _convert_top_with_ties(result)
        result = _convert_waitfor(result)
        result = _convert_rowcount(result, param_names)
        result = _convert_cursor_syntax(result)
        result = _convert_dynamic_sql(result)
        result = _convert_goto_statements(result)
        result = _convert_openjson(result)
        result = _convert_merge(result)
        result = _convert_scope_identity(result)
        result = _convert_select_into(result)          # Fix 3.4: must precede temp_tables
        result = _convert_temp_tables(result)
        result = _add_recursive_to_cte(result)
        result = _convert_select_var_assign(result, params)
        result = _convert_set_var_assign(result, params)
        result = _convert_variable_references(result, param_names)
        # Post-rename passes: variable names are now finalised (p_*/v_* prefix).
        result = _fix_remaining_top(result)          # TOP (@var) → LIMIT p_var at end
        result = _convert_string_concat(result)
        result = _convert_money_type_in_declare(result)
        result = _fix_remaining_top(result)
        result = _convert_cursor_fetch_loops(result)
        result = _normalize_insert_into(result)
        result = _convert_static_routine_exec(result)
        result = _convert_quoted_column_aliases(result)
        result = _strip_tsql_query_options(result)
        result = _convert_control_flow(result)
        result = _remove_go_and_batch_sep(result)
        # Fix 3.7-3.9: additional function/syntax conversions applied last
        result = _convert_isnumeric(result)
        result = _convert_format_function(result)

        return result.strip()


# ---------------------------------------------------------------------------
# Body transformation helpers
# ---------------------------------------------------------------------------

def _expand_multi_var_declare(sql: str) -> str:
    """Split multi-variable DECLARE onto separate lines.

    T-SQL allows: DECLARE @a INT, @b INT = 0, @c NVARCHAR(100);
    We split this into one DECLARE per variable so the per-var regex in
    _collect_declare_vars can pick each one up correctly.
    Splits on commas that are followed by a new @variable name.
    TABLE variables (@t TABLE (...)) are left as-is.
    """
    def _split_declare(m: re.Match) -> str:  # type: ignore[type-arg]
        inner = m.group(1).strip()
        # Skip TABLE variable declarations — they have nested commas
        if re.search(r'\bTABLE\s*\(', inner, re.IGNORECASE):
            return m.group(0)
        # Split on commas that are immediately followed by @  (the next variable)
        parts = re.split(r',\s*(?=@)', inner)
        if len(parts) <= 1:
            return m.group(0)
        return '\n'.join(f"DECLARE {p.strip()};" for p in parts if p.strip())

    return re.sub(
        r'\bDECLARE\s+(@\w+.+?)\s*;',
        _split_declare, sql, flags=re.IGNORECASE | re.DOTALL,
    )


_SESSION_SET_PATTERNS = [
    r'SET\s+NOCOUNT\s+(?:ON|OFF)\s*;?',
    r'SET\s+XACT_ABORT\s+(?:ON|OFF)\s*;?',
    r'SET\s+QUOTED_IDENTIFIER\s+(?:ON|OFF)\s*;?',
    r'SET\s+ANSI_NULLS\s+(?:ON|OFF)\s*;?',
    r'SET\s+ARITHABORT\s+(?:ON|OFF)\s*;?',
    r'SET\s+NUMERIC_ROUNDABORT\s+(?:ON|OFF)\s*;?',
    r'SET\s+CONCAT_NULL_YIELDS_NULL\s+(?:ON|OFF)\s*;?',
    r'SET\s+ANSI_PADDING\s+(?:ON|OFF)\s*;?',
    r'SET\s+IDENTITY_INSERT\s+\S+\s+(?:ON|OFF)\s*;?',
    r'SET\s+ROWCOUNT\s+\d+\s*;?',
    r'COMMIT\s+TRANSACTION\s*;?',
    r'COMMIT\s*;',
    r'BEGIN\s+TRANSACTION\s*(?:\w+)?\s*;?',
    r'ROLLBACK\s+TRANSACTION\s*(?:\w+)?\s*;?',
    r'\bUSE\s+\w+\s*;?',
]


def _remove_session_settings(sql: str) -> str:
    for pattern in _SESSION_SET_PATTERNS:
        sql = re.sub(pattern, '', sql, flags=re.IGNORECASE)
    # Remove WITH (NOLOCK) hints globally — must be a final pass so JOIN-clause hints are caught
    sql = re.sub(r'\s+WITH\s*\(\s*NOLOCK\s*\)', '', sql, flags=re.IGNORECASE)
    return sql


def _remove_go_and_batch_sep(sql: str) -> str:
    """Remove GO batch separators."""
    return re.sub(r'^\s*GO\s*$', '', sql, flags=re.IGNORECASE | re.MULTILINE)


def _strip_n_prefix(sql: str) -> str:
    """Remove the N prefix from N'...' unicode string literals."""
    return re.sub(r"\bN'", "'", sql, flags=re.IGNORECASE)


def _convert_print(sql: str) -> str:
    """PRINT 'msg' → RAISE NOTICE '%', 'msg'."""
    return re.sub(
        r"\bPRINT\s+('(?:[^']|'')*'|\w+)\s*;?",
        lambda m: f"RAISE NOTICE '%', {m.group(1)};",
        sql, flags=re.IGNORECASE,
    )


def _convert_raiserror(sql: str) -> str:
    """Convert RAISERROR and THROW to RAISE EXCEPTION."""
    # THROW errnum, 'msg', state;
    sql = re.sub(
        r"\bTHROW\s+\d+\s*,\s*N?'([^']*)'\s*,\s*\d+\s*;?",
        lambda m: f"RAISE EXCEPTION '{m.group(1)}';",
        sql, flags=re.IGNORECASE,
    )
    # Bare THROW; (re-throw in CATCH)
    sql = re.sub(r'\bTHROW\s*;', 'RAISE;', sql, flags=re.IGNORECASE)

    # RAISERROR('literal', sev, state [, args...])
    sql = re.sub(
        r"\bRAISERROR\s*\(\s*N?'([^']*)'\s*,\s*\d+\s*,\s*\d+(?:\s*,[^)]+)?\)\s*(?:WITH\s+\w+)?\s*;?",
        lambda m: (
            f"RAISE EXCEPTION '{_raiserror_fmt(m.group(1))}', {_raiserror_args(m.group(0))};"
            if _has_format_args(m.group(0)) else
            f"RAISE EXCEPTION '{m.group(1)}';"
        ),
        sql, flags=re.IGNORECASE,
    )
    # RAISERROR(@var, sev, state)
    sql = re.sub(
        r"\bRAISERROR\s*\(\s*@(\w+)\s*,\s*\d+\s*,\s*\d+\s*\)\s*(?:WITH\s+\w+)?\s*;?",
        lambda m: f"RAISE EXCEPTION '%', v_{m.group(1)};",
        sql, flags=re.IGNORECASE,
    )
    # Remaining RAISERROR (format-string style)
    sql = re.sub(
        r"\bRAISERROR\s*\([^)]+\)\s*(?:WITH\s+\w+)?\s*;?",
        "RAISE EXCEPTION '/* TODO: review RAISERROR conversion */';",
        sql, flags=re.IGNORECASE,
    )
    return sql


def _has_format_args(raiserror_call: str) -> bool:
    """Detect if RAISERROR has extra substitution arguments beyond sev/state."""
    m = re.search(r'\(([^)]+)\)', raiserror_call)
    if not m:
        return False
    parts = [p.strip() for p in m.group(1).split(',')]
    return len(parts) > 3  # msg, sev, state + at least one format arg


def _raiserror_fmt(msg: str) -> str:
    """Convert RAISERROR %d/%s placeholders to PG %s/%s."""
    return re.sub(r'%[diouxXeEfFgGcs]', '%s', msg)


def _raiserror_args(full_call: str) -> str:
    """Extract the extra args from a RAISERROR call."""
    m = re.search(r'\(([^)]+)\)', full_call)
    if not m:
        return "''"
    parts = [p.strip() for p in m.group(1).split(',')]
    # parts[0]=msg, [1]=sev, [2]=state, [3:]=format args
    extra = parts[3:]
    args = []
    for a in extra:
        if a.startswith('@'):
            args.append(f"v_{a[1:]}")
        else:
            args.append(a)
    return ', '.join(args) if args else "''"


def _convert_try_catch(sql: str) -> str:
    """Convert BEGIN TRY / END TRY / BEGIN CATCH / END CATCH to PL/pgSQL EXCEPTION."""
    sql = re.sub(r'\bBEGIN\s+TRY\b', '', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bEND\s+TRY\b', '', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bBEGIN\s+CATCH\b', 'EXCEPTION\n    WHEN OTHERS THEN', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bEND\s+CATCH\b\s*;?', '', sql, flags=re.IGNORECASE)

    # ERROR_MESSAGE() / ERROR_SEVERITY() / ERROR_STATE() / ERROR_NUMBER()
    sql = re.sub(r'\bERROR_MESSAGE\s*\(\)', 'SQLERRM', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bERROR_NUMBER\s*\(\)', 'SQLSTATE', sql, flags=re.IGNORECASE)
    # Fix 3.10: emit TODO comments so developers know these need review, not silent 0.
    sql = re.sub(
        r'\bERROR_SEVERITY\s*\(\)',
        "0 /* TODO: no PG equivalent for ERROR_SEVERITY */",
        sql, flags=re.IGNORECASE,
    )
    sql = re.sub(
        r'\bERROR_STATE\s*\(\)',
        "0 /* TODO: no PG equivalent for ERROR_STATE */",
        sql, flags=re.IGNORECASE,
    )
    sql = re.sub(r'\bERROR_PROCEDURE\s*\(\)', "''", sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bERROR_LINE\s*\(\)', '0', sql, flags=re.IGNORECASE)

    sql = re.sub(
        r'\bXACT_STATE\s*\(\s*\)',
        "0 /* TODO: XACT_STATE — no PG equivalent for uncommittable transactions */",
        sql,
        flags=re.IGNORECASE,
    )

    # Fix 3.5: @@TRANCOUNT — PL/pgSQL uses implicit transactions; emit TODO comment.
    sql = re.sub(
        r'@@TRANCOUNT(?![a-zA-Z_])',
        "0 /* TODO: @@TRANCOUNT — PL/pgSQL uses implicit transactions */",
        sql, flags=re.IGNORECASE,
    )

    return sql


def _convert_tsql_builtin_functions(sql: str) -> str:
    """Convert common T-SQL built-in functions to their PostgreSQL equivalents."""
    # Date/time
    sql = re.sub(r'\bGETDATE\s*\(\)', 'CURRENT_TIMESTAMP', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bGETUTCDATE\s*\(\)', "CURRENT_TIMESTAMP AT TIME ZONE 'UTC'", sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bSYSDATETIME\s*\(\)', 'CURRENT_TIMESTAMP', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bNEWID\s*\(\)', 'gen_random_uuid()', sql, flags=re.IGNORECASE)

    # String functions
    sql = re.sub(r'\bLEN\s*\(', 'LENGTH(', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bISNULL\s*\(', 'COALESCE(', sql, flags=re.IGNORECASE)
    # Fix 3.1: CHARINDEX(substring, string) → STRPOS(string, substring) — args are swapped.
    sql = _convert_charindex(sql)
    sql = re.sub(r'\bREPLICATE\s*\(', 'REPEAT(', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bCEILING\s*\(', 'CEIL(', sql, flags=re.IGNORECASE)
    # Fix 3.2: STR(expr[, width[, decimals]]) → CAST(expr AS TEXT) or TO_CHAR with format mask.
    sql = _convert_str_function(sql)

    # QUOTENAME → quote_ident
    sql = re.sub(r'\bQUOTENAME\s*\(', 'quote_ident(', sql, flags=re.IGNORECASE)

    # System functions
    sql = re.sub(r'\bDB_NAME\s*\(\)', 'current_database()', sql, flags=re.IGNORECASE)
    sql = re.sub(r"SERVERPROPERTY\s*\(\s*'ServerName'\s*\)", "current_setting('server_version')", sql, flags=re.IGNORECASE)
    sql = re.sub(r"SERVERPROPERTY\s*\(\s*'ProductVersion'\s*\)", 'version()', sql, flags=re.IGNORECASE)
    sql = re.sub(r'@@VERSION(?![a-zA-Z_])', 'version()', sql, flags=re.IGNORECASE)
    sql = re.sub(r'@@SPID(?![a-zA-Z_])', 'pg_backend_pid()', sql, flags=re.IGNORECASE)

    # Boolean 0/1 for BIT columns (conservative – only obvious patterns)
    # We convert Discontinued = 0/1 etc. but leave arithmetic alone
    sql = re.sub(r'\bDiscontinued\s*=\s*0\b', 'Discontinued = FALSE', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bDiscontinued\s*=\s*1\b', 'Discontinued = TRUE', sql, flags=re.IGNORECASE)

    return sql


def _convert_year_month_day(sql: str) -> str:
    """YEAR(e) → EXTRACT(YEAR FROM e), etc."""

    def _repl(fn: str, sql_in: str) -> str:
        return re.sub(
            rf'\b{fn}\s*\(([^)]+)\)',
            lambda m: f"EXTRACT({fn.upper()} FROM {m.group(1)})",
            sql_in, flags=re.IGNORECASE,
        )

    for fn in ("YEAR", "MONTH", "DAY"):
        sql = _repl(fn, sql)

    # DATEPART(yy|year, expr) → EXTRACT(YEAR FROM expr)
    _dp_map = {
        'yy': 'YEAR', 'yyyy': 'YEAR', 'year': 'YEAR',
        'mm': 'MONTH', 'm': 'MONTH', 'month': 'MONTH',
        'dd': 'DAY', 'd': 'DAY', 'day': 'DAY',
        'hh': 'HOUR', 'hour': 'HOUR',
        'mi': 'MINUTE', 'n': 'MINUTE', 'minute': 'MINUTE',
        'ss': 'SECOND', 's': 'SECOND', 'second': 'SECOND',
        'ms': 'MILLISECONDS', 'millisecond': 'MILLISECONDS',
        'wk': 'WEEK', 'ww': 'WEEK', 'week': 'WEEK',
        'q': 'QUARTER', 'qq': 'QUARTER', 'quarter': 'QUARTER',
        'dy': 'DOY', 'dayofyear': 'DOY',
        'dw': 'DOW', 'weekday': 'DOW',
    }

    def _dp_repl(m: re.Match) -> str:  # type: ignore[type-arg]
        part = m.group(1).strip().lower().strip("'")
        expr = m.group(2).strip()
        pg_part = _dp_map.get(part, part.upper())
        return f"EXTRACT({pg_part} FROM {expr})"

    sql = re.sub(
        r'\bDATEPART\s*\(\s*(\w+)\s*,\s*([^)]+)\)',
        _dp_repl, sql, flags=re.IGNORECASE,
    )

    # DATEDIFF(unit, start, end) — Fix 3.3: sub-day units must use EPOCH arithmetic.
    # EXTRACT(SECOND FROM interval) returns only the seconds component (0–59), not total
    # seconds elapsed.  Use EXTRACT(EPOCH ...) to get the correct total count.
    def _dd_repl(m: re.Match) -> str:  # type: ignore[type-arg]
        part = m.group(1).strip().lower().strip("'")
        start = m.group(2).strip()
        end = m.group(3).strip()
        pg_part = _dp_map.get(part, part.upper())
        if pg_part in ('SECOND',):
            return (
                f"EXTRACT(EPOCH FROM ({end}::TIMESTAMPTZ - {start}::TIMESTAMPTZ))::BIGINT"
            )
        if pg_part in ('MINUTE',):
            return (
                f"(EXTRACT(EPOCH FROM ({end}::TIMESTAMPTZ - {start}::TIMESTAMPTZ)) / 60)::BIGINT"
            )
        if pg_part in ('HOUR',):
            return (
                f"(EXTRACT(EPOCH FROM ({end}::TIMESTAMPTZ - {start}::TIMESTAMPTZ)) / 3600)::BIGINT"
            )
        if pg_part in ('DAY',):
            return (
                f"(EXTRACT(EPOCH FROM ({end}::TIMESTAMPTZ - {start}::TIMESTAMPTZ)) / 86400)::BIGINT"
            )
        if pg_part in ('YEAR',):
            return f"EXTRACT(YEAR FROM AGE({end}, {start}))"
        if pg_part in ('MONTH',):
            return f"(EXTRACT(YEAR FROM AGE({end}, {start})) * 12 + EXTRACT(MONTH FROM AGE({end}, {start})))"
        return f"EXTRACT({pg_part} FROM ({end} - {start}))"

    sql = re.sub(
        r'\bDATEDIFF\s*\(\s*(\w+)\s*,\s*([^,)]+)\s*,\s*([^)]+)\)',
        _dd_repl, sql, flags=re.IGNORECASE,
    )

    # DATEADD(unit, n, date) → date + INTERVAL 'n units'
    def _da_repl(m: re.Match) -> str:  # type: ignore[type-arg]
        part = m.group(1).strip().lower()
        amount_raw = m.group(2).strip()
        date_expr = m.group(3).strip()
        _unit_map = {
            'year': 'year', 'yy': 'year', 'yyyy': 'year',
            'month': 'month', 'mm': 'month', 'm': 'month',
            'day': 'day', 'dd': 'day', 'd': 'day',
            'week': 'week', 'wk': 'week', 'ww': 'week',
            'hour': 'hour', 'hh': 'hour',
            'minute': 'minute', 'mi': 'minute', 'n': 'minute',
            'second': 'second', 'ss': 'second', 's': 'second',
        }
        unit = _unit_map.get(part, part)
        # Handle variable amounts
        if amount_raw.lstrip('-').isdigit():
            n = int(amount_raw)
            sign = '+' if n >= 0 else '-'
            return f"({date_expr} {sign} INTERVAL '{abs(n)} {unit}s')"
        # Variable amount → use * operator form
        return f"({date_expr} + ({amount_raw} * INTERVAL '1 {unit}'))"

    sql = re.sub(
        r'\bDATEADD\s*\(\s*(\w+)\s*,\s*([^,)]+)\s*,\s*([^)]+)\)',
        _da_repl, sql, flags=re.IGNORECASE,
    )

    return sql


def _convert_convert_function(sql: str) -> str:
    """CONVERT(type, expr[, style]) → CAST(expr AS type)."""

    def _repl(m: re.Match) -> str:  # type: ignore[type-arg]
        target = m.group(1).strip()
        expr = m.group(2).strip()
        # style = m.group(3)  -- ignored for now
        pg_type = TsqlTypeMapper.map(target)
        return f"CAST({expr} AS {pg_type})"

    # With style code
    sql = re.sub(
        r'\bCONVERT\s*\(\s*([\w\s\(\)]+?)\s*,\s*([^,)]+(?:\([^)]*\))?)\s*(?:,\s*\d+)?\s*\)',
        _repl, sql, flags=re.IGNORECASE,
    )
    # TRY_CONVERT / TRY_CAST
    sql = re.sub(
        r'\bTRY_CONVERT\s*\(\s*([\w\s\(\)]+?)\s*,\s*([^,)]+)\s*\)',
        _repl, sql, flags=re.IGNORECASE,
    )
    return sql


def _convert_iif_single_pass(sql: str) -> str:
    """One balanced-paren pass converting IIF(cond,tv,fv) → CASE WHEN cond THEN tv ELSE fv END."""
    result: list[str] = []
    pos = 0
    pattern = re.compile(r'\bIIF\s*\(', re.IGNORECASE)
    while pos < len(sql):
        m = pattern.search(sql, pos)
        if not m:
            result.append(sql[pos:])
            break
        result.append(sql[pos:m.start()])
        inner_start = m.end()
        depth = 1
        j = inner_start
        while j < len(sql) and depth > 0:
            if sql[j] == '(':
                depth += 1
            elif sql[j] == ')':
                depth -= 1
            j += 1
        inner = sql[inner_start:j - 1]
        parts = _split_top_level(inner, ',')
        if len(parts) == 3:
            cond, tv, fv = (p.strip() for p in parts)
            result.append(f"CASE WHEN {cond} THEN {tv} ELSE {fv} END")
        else:
            result.append(m.group(0) + inner + ')')
        pos = j
    return ''.join(result)


def _convert_iif(sql: str) -> str:
    """IIF(cond, true_val, false_val) → CASE WHEN cond THEN true_val ELSE false_val END.

    Iterates until no more IIF remain, so nested IIF(a, b, IIF(c, d, e)) patterns
    are fully expanded in multiple passes.
    """
    prev = None
    while prev != sql:
        prev = sql
        sql = _convert_iif_single_pass(sql)
    return sql


def _split_top_level(s: str, sep: str) -> list[str]:
    """Split s on sep only when not inside parentheses."""
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in s:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        if ch == sep and depth == 0:
            parts.append(''.join(current))
            current = []
        else:
            current.append(ch)
    if current:
        parts.append(''.join(current))
    return parts


def _convert_charindex(sql: str) -> str:
    """Fix 3.1: CHARINDEX(substring, string[, start]) → STRPOS(string, substring).

    T-SQL argument order: (needle, haystack[, start])
    PostgreSQL STRPOS order: (haystack, needle)
    The old code only renamed the function without swapping, producing wrong SQL.
    """
    def _repl(m: re.Match) -> str:  # type: ignore[type-arg]
        inner = m.group(1)
        args = _split_top_level(inner, ',')
        if len(args) >= 2:
            needle = args[0].strip()
            haystack = args[1].strip()
            if len(args) >= 3:
                # 3-arg form: CHARINDEX(needle, haystack, start) — no direct PG equivalent;
                # approximate with POSITION starting workaround using SUBSTRING.
                start = args[2].strip()
                return (
                    f"(CASE WHEN STRPOS(SUBSTRING({haystack} FROM {start}), {needle}) > 0 "
                    f"THEN STRPOS(SUBSTRING({haystack} FROM {start}), {needle}) + ({start}) - 1 "
                    f"ELSE 0 END)"
                )
            return f"STRPOS({haystack}, {needle})"
        return m.group(0)  # fallback: leave unchanged

    return re.sub(
        r'\bCHARINDEX\s*\(([^;]+?)\)',
        _repl, sql, flags=re.IGNORECASE,
    )


def _convert_str_function(sql: str) -> str:
    """Fix 3.2: STR(expr[, width[, decimals]]) → proper PostgreSQL equivalent.

    T-SQL STR(value, length, decimals) pads/truncates numeric to string.
    - STR(expr)           → CAST(expr AS TEXT)
    - STR(expr, w)        → CAST(expr AS TEXT)  (width only, no decimals)
    - STR(expr, w, d)     → TO_CHAR(expr, format_mask) where mask is built from decimals
    The old code just renamed STR → TO_CHAR without the required format string argument,
    producing invalid PostgreSQL syntax.
    """
    def _repl(m: re.Match) -> str:  # type: ignore[type-arg]
        inner = m.group(1)
        args = _split_top_level(inner, ',')
        expr = args[0].strip()
        if len(args) == 1:
            return f"CAST({expr} AS TEXT)"
        if len(args) == 2:
            return f"CAST({expr} AS TEXT)"
        # 3-arg form: STR(expr, width, decimals)
        decimals = args[2].strip()
        try:
            d = int(decimals)
            if d == 0:
                fmt = "'FM99999999990'"
            else:
                fmt = f"'FM99999999990.{'0' * d}'"
        except ValueError:
            # Variable decimals — build format dynamically
            fmt = f"('FM99999999990.' || REPEAT('0', {decimals}))"
        return f"TO_CHAR({expr}, {fmt})"

    return re.sub(
        r'\bSTR\s*\(([^;)]+(?:\([^)]*\)[^;)]*)*)\)',
        _repl, sql, flags=re.IGNORECASE,
    )


def _convert_select_into(sql: str) -> str:
    """Fix 3.4: SELECT cols INTO [#]table FROM source → CREATE [TEMP] TABLE ... AS SELECT.

    T-SQL SELECT INTO creates a new table from a query result.
    PostgreSQL uses CREATE TABLE AS SELECT or CREATE TEMP TABLE AS SELECT.
    """
    def _repl(m: re.Match) -> str:  # type: ignore[type-arg]
        cols = m.group(1).strip()
        new_table_raw = m.group(2).strip()
        source_and_rest = m.group(3).strip()
        is_temp = new_table_raw.startswith('#')
        new_table = new_table_raw.lstrip('#').lstrip('@')
        temp_kw = "TEMP " if is_temp else ""
        return f"CREATE {temp_kw}TABLE {new_table} AS SELECT {cols} FROM {source_and_rest}"

    return re.sub(
        r'\bSELECT\s+(.+?)\s+INTO\s+([#@]?\w+)\s+FROM\s+(.+?)(?=\s*;|\s*$)',
        _repl, sql, flags=re.IGNORECASE | re.DOTALL,
    )


def _convert_choose(sql: str) -> str:
    """CHOOSE(n, v1, v2, ...) → (ARRAY[v1, v2, ...])[n]."""

    def _repl(m: re.Match) -> str:  # type: ignore[type-arg]
        inner = m.group(1)
        parts = _split_top_level(inner, ',')
        if len(parts) < 2:
            return m.group(0)
        idx = parts[0].strip()
        vals = ', '.join(p.strip() for p in parts[1:])
        return f"(ARRAY[{vals}])[{idx}]"

    return re.sub(r'\bCHOOSE\s*\((.+?)\)', _repl, sql, flags=re.IGNORECASE | re.DOTALL)


def _convert_top_with_ties(sql: str) -> str:
    """
    SELECT TOP (n) WITH TIES ... ORDER BY col
    → SELECT ... ORDER BY col LIMIT n  (emitting DENSE_RANK note for manual review).
    """
    # TOP (n) WITH TIES  – strip WITH TIES, convert TOP n to LIMIT
    sql = re.sub(
        r'\bTOP\s*\(\s*(\w+)\s*\)\s+WITH\s+TIES\b',
        lambda m: f"/* TOP {m.group(1)} WITH TIES: use DENSE_RANK() subquery for exact semantics */",
        sql, flags=re.IGNORECASE,
    )
    sql = re.sub(
        r'\bTOP\s+(\d+)\s+WITH\s+TIES\b',
        lambda m: f"/* TOP {m.group(1)} WITH TIES: use DENSE_RANK() subquery */ LIMIT {m.group(1)}",
        sql, flags=re.IGNORECASE,
    )
    # Remaining bare WITH TIES
    sql = re.sub(r'\bWITH\s+TIES\b', '', sql, flags=re.IGNORECASE)

    # Convert simple TOP (n) → LIMIT n  (without WITH TIES)
    sql = re.sub(
        r'\bTOP\s*\(\s*(\w+)\s*\)',
        lambda m: f"LIMIT {m.group(1)}",
        sql, flags=re.IGNORECASE,
    )
    # TOP n (without parens) — use comment placeholder; _fix_remaining_top()
    # handles the structural move of LIMIT to end-of-statement later.
    sql = re.sub(
        r'\bSELECT\s+TOP\s+(\d+)\b',
        lambda m: f"SELECT /* LIMIT {m.group(1)} GOES TO END */ ",
        sql, flags=re.IGNORECASE,
    )

    return sql


def _find_select_terminator(sql: str, start: int) -> int:
    """Return index of the first ``;`` or ``)`` at parenthesis depth zero."""
    depth = 0
    i = start
    in_sq = False
    in_dq = False
    while i < len(sql):
        ch = sql[i]
        if in_sq:
            if ch == "'" and i + 1 < len(sql) and sql[i + 1] == "'":
                i += 2
                continue
            if ch == "'":
                in_sq = False
            i += 1
            continue
        if in_dq:
            if ch == '"':
                in_dq = False
            i += 1
            continue
        if ch == "'":
            in_sq = True
            i += 1
            continue
        if ch == '"':
            in_dq = True
            i += 1
            continue
        if ch == '(':
            depth += 1
        elif ch == ')':
            if depth == 0:
                return i
            depth -= 1
        elif ch == ';' and depth == 0:
            return i
        i += 1
    return len(sql)


def _append_limit_to_select(
    sql: str,
    pattern: re.Pattern[str],
    limit_group: int,
) -> str:
    """Rewrite SELECT matches so ``LIMIT <expr>`` is appended at statement end."""
    parts: list[str] = []
    last = 0
    for m in pattern.finditer(sql):
        parts.append(sql[last:m.start()])
        prefix = m.group(1) or ''
        limit_expr = m.group(limit_group).strip()
        body_start = m.end()
        body_end = _find_select_terminator(sql, body_start)
        body = sql[body_start:body_end].strip()
        parts.append(f"{prefix}SELECT {body} LIMIT {limit_expr}")
        last = body_end
    parts.append(sql[last:])
    return ''.join(parts)


def _fix_remaining_top(sql: str) -> str:
    """Post-rename pass: move SELECT TOP / LIMIT placeholders to end-of-SELECT.

    This runs *after* ``_convert_variable_references`` so parameter names like
    ``p_TopN`` are already in their final form and can be used directly as the
    LIMIT expression.

    Handles:
    - ``SELECT /* LIMIT n GOES TO END */`` placeholders from ``_convert_top_with_ties``
    - ``SELECT TOP (expr)`` including subqueries ending with ``)`` not just ``;``
    """
    sql = _append_limit_to_select(
        sql,
        re.compile(
            r'\b((?:RETURN\s+QUERY\s+)?)SELECT\s*/\*\s*LIMIT\s+(\d+)\s+GOES\s+TO\s+END\s*\*/\s*',
            re.IGNORECASE,
        ),
        limit_group=2,
    )
    sql = _append_limit_to_select(
        sql,
        re.compile(
            r'\b((?:RETURN\s+QUERY\s+)?)SELECT\s+TOP\s*\(\s*([^)]+?)\s*\)\s*',
            re.IGNORECASE,
        ),
        limit_group=2,
    )
    return sql


def _convert_waitfor(sql: str) -> str:
    """WAITFOR DELAY 'HH:MM:SS' → PERFORM pg_sleep(seconds)."""

    def _repl(m: re.Match) -> str:  # type: ignore[type-arg]
        t = m.group(1).strip("'")
        parts = t.split(':')
        try:
            secs = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        except (ValueError, IndexError):
            secs = 0
        return f"PERFORM pg_sleep({secs});"

    return re.sub(
        r"\bWAITFOR\s+DELAY\s+'([^']+)'\s*;?",
        _repl, sql, flags=re.IGNORECASE,
    )


def _convert_rowcount(sql: str, param_names: set[str] | None = None) -> str:
    """@@ROWCOUNT usage patterns → GET DIAGNOSTICS v_rowcount = ROW_COUNT."""
    pnames = param_names or set()

    # SET @var = @@ROWCOUNT → GET DIAGNOSTICS p_var/v_var = ROW_COUNT;
    def _rc_repl(m: re.Match) -> str:  # type: ignore[type-arg]
        vname = m.group(1)
        prefix = "p_" if vname.upper() in pnames else "v_"
        return f"GET DIAGNOSTICS {prefix}{vname} = ROW_COUNT;"

    sql = re.sub(
        r'SET\s+@(\w+)\s*=\s*@@ROWCOUNT\s*;?',
        _rc_repl, sql, flags=re.IGNORECASE,
    )

    # IF @@ROWCOUNT = 0 → IF NOT FOUND
    sql = re.sub(r'IF\s+@@ROWCOUNT\s*=\s*0\b', 'IF NOT FOUND', sql, flags=re.IGNORECASE)
    # IF @@ROWCOUNT > 0 → IF FOUND
    sql = re.sub(r'IF\s+@@ROWCOUNT\s*>\s*0\b', 'IF FOUND', sql, flags=re.IGNORECASE)

    # Remaining @@ROWCOUNT references
    sql = re.sub(r'@@ROWCOUNT(?![a-zA-Z_])', 'v_rowcount', sql, flags=re.IGNORECASE)

    return sql


def _convert_openjson(sql: str) -> str:
    """Convert OPENJSON(@json) WITH (col TYPE 'path', ...) to jsonb_to_recordset form.

    Simple form: FROM OPENJSON(@json) WITH (col1 TYPE '$.x', col2 TYPE '$.y')
    → FROM jsonb_to_recordset(@json::jsonb) AS t(col1 TYPE, col2 TYPE)

    Only handles the WITH clause form; bare OPENJSON without WITH is left alone.
    """
    def _repl(m: re.Match) -> str:  # type: ignore[type-arg]
        json_arg = m.group(1).strip()
        with_body = m.group(2)
        # json_arg may be @var or a variable with path: @var, 'path'
        if json_arg.startswith('@'):
            json_expr = f"v_{json_arg[1:]}::jsonb"
        else:
            # Strip possible N' prefix
            json_arg = re.sub(r"^N'", "'", json_arg)
            json_expr = f"{json_arg}::jsonb"

        # Parse WITH clause: each item is "col_name TYPE 'json_path'"
        # Strip the path strings to extract just col TYPE pairs
        col_defs = re.sub(r"'[^']*'", '', with_body)  # remove json path strings
        # Collapse extra whitespace left by removed paths
        col_defs = re.sub(r'\s{2,}', ' ', col_defs).strip()
        # Map types
        def _map_col_type(col_def: str) -> str:
            parts = col_def.strip().split()
            if len(parts) >= 2:
                name = parts[0]
                raw_type = ' '.join(parts[1:])
                pg_type = TsqlTypeMapper.map(raw_type)
                return f"{name} {pg_type}"
            return col_def.strip()

        cols = [_map_col_type(c) for c in _split_top_level(col_defs, ',') if c.strip()]
        col_list = ', '.join(cols)
        return f"jsonb_to_recordset({json_expr}) AS t({col_list})"

    # Use balanced-paren scanning since WITH body may contain type parens like CHAR(5)
    result: list[str] = []
    pos = 0
    oj_pat = re.compile(r'\bOPENJSON\s*\(', re.IGNORECASE)
    with_pat = re.compile(r'\s+WITH\s*\(', re.IGNORECASE)
    while pos < len(sql):
        m = oj_pat.search(sql, pos)
        if not m:
            result.append(sql[pos:])
            break
        result.append(sql[pos:m.start()])
        # Find the close of OPENJSON(...)
        arg_start = m.end()
        depth = 1
        j = arg_start
        while j < len(sql) and depth > 0:
            if sql[j] == '(':
                depth += 1
            elif sql[j] == ')':
                depth -= 1
            j += 1
        json_arg = sql[arg_start:j - 1].strip()
        # Now look for WITH (
        wm = with_pat.match(sql, j)
        if wm:
            with_start = wm.end()
            depth2 = 1
            k = with_start
            while k < len(sql) and depth2 > 0:
                if sql[k] == '(':
                    depth2 += 1
                elif sql[k] == ')':
                    depth2 -= 1
                k += 1
            with_body = sql[with_start:k - 1]
            # Build the fake match-group and call _repl logic inline
            if json_arg.startswith('@'):
                json_expr = f"v_{json_arg[1:]}::jsonb"
            else:
                json_arg2 = re.sub(r"^N'", "'", json_arg)
                json_expr = f"{json_arg2}::jsonb"
            col_defs = re.sub(r"'[^']*'", '', with_body)
            col_defs = re.sub(r'\s{2,}', ' ', col_defs).strip()

            def _map_col_type(col_def: str) -> str:
                parts2 = col_def.strip().split()
                if len(parts2) >= 2:
                    cname = parts2[0]
                    raw_t = ' '.join(parts2[1:])
                    return f"{cname} {TsqlTypeMapper.map(raw_t)}"
                return col_def.strip()

            cols = [_map_col_type(c) for c in _split_top_level(col_defs, ',') if c.strip()]
            result.append(f"jsonb_to_recordset({json_expr}) AS t({', '.join(cols)})")
            pos = k
        else:
            # No WITH clause — leave OPENJSON as-is with a TODO comment
            result.append(f"/* TODO: convert OPENJSON */ OPENJSON({json_arg})")
            pos = j
    return ''.join(result)


def _convert_merge(sql: str) -> str:
    """Convert simple SQL Server MERGE to PostgreSQL INSERT … ON CONFLICT.

    Handles the canonical pattern:
      MERGE INTO target AS t
      USING source AS s ON join_cond
      WHEN MATCHED THEN UPDATE SET col=s.col, …
      WHEN NOT MATCHED THEN INSERT (cols) VALUES (vals);

    Complex forms (OUTPUT $ACTION, WHEN NOT MATCHED BY SOURCE, multiple WHEN
    MATCHED clauses) get a TODO comment inserted before the statement so the
    developer knows manual work is required.

    MERGE inside a string literal (dynamic SQL) is left unchanged.
    """
    # Balanced-scan approach: locate each MERGE block and try to convert it.
    result: list[str] = []
    pos = 0
    merge_pat = re.compile(
        r'(?<!["\'])(?:^|\n)(\s*)MERGE\s+INTO\b',
        re.IGNORECASE | re.MULTILINE,
    )

    while pos < len(sql):
        m = merge_pat.search(sql, pos)
        if not m:
            result.append(sql[pos:])
            break

        result.append(sql[pos:m.start()])
        indent = m.group(1)

        # Collect the full MERGE statement up to the terminating ;
        stmt_start = m.start() + len(m.group(0)) - len("MERGE INTO")
        semi = sql.find(';', stmt_start)
        if semi == -1:
            result.append(sql[stmt_start:])
            pos = len(sql)
            break

        stmt = sql[stmt_start:semi + 1]

        converted = _try_convert_merge(stmt, indent)
        result.append(converted)
        pos = semi + 1

    return ''.join(result)


def _try_convert_merge(stmt: str, indent: str) -> str:
    """Attempt to convert a single MERGE statement; return TODO comment on failure."""
    # Parse: MERGE INTO target [AS alias] USING (src) [AS salias] ON cond
    #        WHEN MATCHED THEN UPDATE SET ...
    #        WHEN NOT MATCHED [BY TARGET] THEN INSERT (cols) VALUES (vals)
    header_m = re.match(
        r'MERGE\s+INTO\s+([\w\.]+)(?:\s+AS\s+(\w+))?\s+'
        r'USING\s+(.+?)\s+AS\s+(\w+)\s+ON\s+(.+?)\s+'
        r'(?=WHEN\b)',
        stmt, re.IGNORECASE | re.DOTALL,
    )
    if not header_m:
        return _merge_todo(stmt, indent)

    target = header_m.group(1)
    src_query = header_m.group(3).strip()
    src_alias = header_m.group(4)
    on_cond = header_m.group(5).strip()

    rest = stmt[header_m.end():]

    # Bail on complex forms we can't auto-convert
    if re.search(r'OUTPUT\s+\$ACTION', rest, re.IGNORECASE):
        return _merge_todo(stmt, indent)
    if re.search(r'WHEN\s+NOT\s+MATCHED\s+BY\s+SOURCE', rest, re.IGNORECASE):
        return _merge_todo(stmt, indent)
    # Count WHEN MATCHED clauses – more than one means complex update logic
    if len(re.findall(r'\bWHEN\s+MATCHED\b', rest, re.IGNORECASE)) > 1:
        return _merge_todo(stmt, indent)

    # Extract WHEN MATCHED UPDATE SET …
    upd_m = re.search(
        r'WHEN\s+MATCHED\s+THEN\s+UPDATE\s+SET\s+(.+?)(?=WHEN\b|;)',
        rest, re.IGNORECASE | re.DOTALL,
    )
    # Extract WHEN NOT MATCHED INSERT …
    ins_m = re.search(
        r'WHEN\s+NOT\s+MATCHED(?:\s+BY\s+TARGET)?\s+THEN\s+INSERT\s*\(([^)]+)\)\s+VALUES\s*\(([^)]+)\)',
        rest, re.IGNORECASE | re.DOTALL,
    )

    if not ins_m:
        return _merge_todo(stmt, indent)

    ins_cols = ins_m.group(1).strip()
    ins_vals = ins_m.group(2).strip()

    # Derive ON CONFLICT columns from the ON condition
    # ON t.col1 = s.col1 AND t.col2 = s.col2  → (col1, col2)
    conflict_cols_raw = re.findall(
        r'(?:\w+\.)?(\w+)\s*=\s*(?:\w+\.)?(?:\w+)',
        on_cond, re.IGNORECASE,
    )
    conflict_cols = ', '.join(dict.fromkeys(conflict_cols_raw))  # dedupe, keep order

    lines: list[str] = []
    if src_query.startswith('('):
        lines.append(f"{indent}INSERT INTO {target} ({ins_cols})")
        lines.append(f"{indent}SELECT {ins_vals.replace(f'{src_alias}.', '')}")
        lines.append(f"{indent}FROM {src_query} AS {src_alias}")
    else:
        lines.append(f"{indent}INSERT INTO {target} ({ins_cols})")
        lines.append(f"{indent}SELECT {ins_vals}")
        lines.append(f"{indent}FROM ({src_query}) AS {src_alias}")

    if conflict_cols:
        lines.append(f"{indent}ON CONFLICT ({conflict_cols}) DO")
    else:
        lines.append(f"{indent}ON CONFLICT DO")

    if upd_m:
        set_clause = upd_m.group(1).strip().rstrip(';').rstrip()
        lines.append(f"{indent}    UPDATE SET {set_clause};")
    else:
        lines.append(f"{indent}    NOTHING;")

    return '\n'.join(lines)


def _merge_todo(stmt: str, indent: str) -> str:
    """Wrap an unconvertible MERGE statement with a TODO comment."""
    return (
        f"{indent}/* TODO: convert MERGE manually — "
        "use INSERT … ON CONFLICT or CTE with RETURNING */\n"
        + stmt
    )


def _convert_cursor_fetch_loops(sql: str) -> str:
    """Convert DECLARE CURSOR + WHILE @@FETCH_STATUS loops to PL/pgSQL FOR ... LOOP."""
    pattern = re.compile(
        r"DECLARE\s+(?P<cursor>@?\w+)\s+CURSOR\s+FOR\s+"
        r"(?P<query>SELECT[\s\S]+?)\s*;\s*"
        r"OPEN\s+(?P=cursor)\s*;\s*"
        r"FETCH\s+(?:NEXT\s+)?FROM\s+(?P=cursor)\s+INTO\s+(?P<var>@?\w+)\s*;\s*"
        r"WHILE\s+(?:@@FETCH_STATUS\s*=\s*0|FOUND(?:\s*=\s*0)?)\s*"
        r"BEGIN\s*"
        r"(?P<body>[\s\S]*?)"
        r"END\s*"
        r"(?:\s*CLOSE\s+(?P=cursor)\s*;\s*)?"
        r"(?:\s*DEALLOCATE\s+(?P=cursor)\s*;\s*)?",
        re.IGNORECASE,
    )

    def _repl(m: re.Match) -> str:  # type: ignore[type-arg]
        query = m.group("query").strip()
        var = m.group("var")
        var_plain = var.lstrip("@")
        loop_var = var_plain if var_plain.startswith(("v_", "p_")) else f"v_{var_plain}"
        cursor_pat = re.escape(m.group("cursor"))
        body = m.group("body").strip()
        body = re.sub(
            rf"FETCH\s+(?:NEXT\s+)?FROM\s+{cursor_pat}\s+INTO\s+{re.escape(var)}\s*;?\s*",
            "",
            body,
            flags=re.IGNORECASE,
        )
        indented = "\n".join(
            f"    {line}" if line.strip() else line for line in body.split("\n")
        )
        return f"FOR {loop_var} IN {query} LOOP\n{indented}\nEND LOOP;"

    return pattern.sub(_repl, sql)


def _convert_cursor_syntax(sql: str) -> str:
    """Remove SQL Server cursor modifiers and convert @@FETCH_STATUS."""
    # CURSOR LOCAL FAST_FORWARD / CURSOR STATIC / CURSOR FORWARD_ONLY → CURSOR
    sql = re.sub(
        r'\bCURSOR\s+(?:LOCAL\s+)?(?:FAST_FORWARD\s+)?(?:STATIC\s+)?(?:FORWARD_ONLY\s+)?(?:SCROLL\s+)?(?:READ_ONLY\s+)?FOR\b',
        'CURSOR FOR',
        sql, flags=re.IGNORECASE,
    )
    # WHILE @@FETCH_STATUS = 0 → WHILE FOUND
    sql = re.sub(r'@@FETCH_STATUS\s*=\s*0\b', 'FOUND', sql, flags=re.IGNORECASE)
    sql = re.sub(r'@@FETCH_STATUS\s*<>\s*0\b', 'NOT FOUND', sql, flags=re.IGNORECASE)
    sql = re.sub(r'@@FETCH_STATUS\s*!=\s*0\b', 'NOT FOUND', sql, flags=re.IGNORECASE)
    # DEALLOCATE cursor → nothing (PL/pgSQL cursors don't need explicit deallocation)
    sql = re.sub(r'\bDEALLOCATE\s+\w+\s*;?', '', sql, flags=re.IGNORECASE)
    return sql


def _convert_dynamic_sql(sql: str) -> str:
    """Convert EXEC/EXECUTE sp_executesql and EXEC @var to PL/pgSQL EXECUTE."""
    def _exec_sp_repl(m: re.Match) -> str:  # type: ignore[type-arg]
        raw_var = m.group(1)
        var_name = raw_var.lstrip("@")
        params_raw = m.group(2) or ""
        vals = re.findall(r"@\w+\s*=\s*([^,;]+)", params_raw)
        if not vals:
            vals = [
                p.strip()
                for p in re.split(r",", params_raw)
                if p.strip() and not re.match(r"N['\"]", p.strip(), re.IGNORECASE)
            ]
        if vals:
            using_clause = ", ".join(
                f"v_{v.strip().lstrip('@')}" if v.strip().startswith("@") else v.strip()
                for v in vals
            )
            return f"EXECUTE v_{var_name} USING {using_clause};"
        return f"EXECUTE v_{var_name};"

    _sp_exec_re = re.compile(
        r"\b(?:EXEC(?:UTE)?)\s+(?:(?:\[\w+\]\.)?(?:\[sp_executesql\]|sp_executesql))\s+"
        r"(@?\w+)((?:\s*,\s*[^;]+)*)\s*;?",
        re.IGNORECASE,
    )
    sql = _sp_exec_re.sub(_exec_sp_repl, sql)
    sql = re.sub(
        r"\bEXEC\s+@(\w+)\s*;",
        lambda m: f"EXECUTE v_{m.group(1)};",
        sql,
        flags=re.IGNORECASE,
    )
    sql = re.sub(
        r"\bEXEC\s*\(\s*('(?:[^']|'')*')\s*\)\s*;?",
        r"EXECUTE \1;",
        sql,
        flags=re.IGNORECASE,
    )
    from domains.transpilation.converters.dynamic_sql_converter import DynamicSqlConverter

    return DynamicSqlConverter.apply_all(sql).sql


def _convert_goto_statements(sql: str) -> str:
    """Convert T-SQL GOTO/labels to PL/pgSQL-safe placeholders (no GOTO keyword left)."""
    result = re.sub(
        r"\bIF\s+(.+?)\s+GOTO\s+(\w+)\s+THEN\b",
        r"IF \1 THEN NULL; /* jump to label \2 — restructure manually */ END IF",
        sql,
        flags=re.IGNORECASE,
    )
    result = re.sub(
        r"\bIF\s+(.+?)\s+GOTO\s+(\w+)\b",
        r"IF \1 THEN NULL; /* jump to label \2 — restructure manually */ END IF",
        result,
        flags=re.IGNORECASE,
    )
    result = re.sub(
        r"\bGOTO\s+(\w+)\s*;?",
        r"NULL; /* jump to label \1 — restructure manually */",
        result,
        flags=re.IGNORECASE,
    )
    result = re.sub(
        r"(?m)^(\s*)([A-Za-z_]\w*)\s*:",
        r"\1-- label \2",
        result,
    )
    result = re.sub(r"/\*\s*label:(\w+)\s*\*/", r"-- label \1", result, flags=re.IGNORECASE)
    result = re.sub(r"\bEND IF;\s+THEN\b", "END IF", result, flags=re.IGNORECASE)
    return result


def _normalize_insert_into(sql: str) -> str:
    """T-SQL INSERT table (cols) without INTO → PostgreSQL INSERT INTO table."""
    return re.sub(
        r'\bINSERT\s+(?!INTO\b)(?=(?:[\w"]+\.)?[\w"]+)',
        "INSERT INTO ",
        sql,
        flags=re.IGNORECASE,
    )


def _convert_static_routine_exec(sql: str) -> str:
    """EXEC/EXECUTE schema.procedure → CALL schema.procedure() for static routine invocations."""
    pattern = re.compile(
        r"\b(?:EXECUTE|EXEC)\s+(?!sp_executesql\b|(?:v_|p_|\())"
        r"(?:(?P<schema>\w+)\.)?(?P<proc>\w+)\s*;?",
        re.IGNORECASE,
    )

    def _repl(m: re.Match[str]) -> str:
        schema = m.group("schema")
        proc = m.group("proc")
        qual = f"{schema}.{proc}" if schema else proc
        return f"CALL {qual}();"

    return pattern.sub(_repl, sql)


def _convert_scope_identity(sql: str) -> str:
    """
    SET @var = SCOPE_IDENTITY() / @@IDENTITY right after INSERT →
    kept as LASTVAL() assignment; full RETURNING rewrite needs AST context.
    The wrapper will emit GET DIAGNOSTICS form for complex cases.
    """
    sql = re.sub(r'\bSCOPE_IDENTITY\s*\(\)', 'LASTVAL()', sql, flags=re.IGNORECASE)
    sql = re.sub(r'@@IDENTITY(?![a-zA-Z_])', 'LASTVAL()', sql, flags=re.IGNORECASE)
    return sql


def _convert_temp_tables(sql: str) -> str:
    """#TempTable → tmp_TempTable, CREATE TABLE #t → CREATE TEMP TABLE tmp_t."""
    # Rename #table references
    sql = re.sub(r'#(\w+)', lambda m: f"tmp_{m.group(1)}", sql)
    # Convert CREATE TABLE tmp_x → CREATE TEMP TABLE tmp_x
    sql = re.sub(
        r'\bCREATE\s+TABLE\s+(tmp_\w+)',
        r'CREATE TEMP TABLE \1',
        sql, flags=re.IGNORECASE,
    )
    return sql


def _add_recursive_to_cte(sql: str) -> str:
    """Detect recursive CTEs (reference themselves) and add RECURSIVE keyword."""

    def _check_and_add(m: re.Match) -> str:  # type: ignore[type-arg]
        cte_name = m.group(1)
        col_list = m.group(2) or ""
        cte_body_start = m.start()
        rest = sql[cte_body_start:]
        self_ref_pattern = re.compile(
            r'\bUNION\s+ALL\b.+?\b' + re.escape(cte_name) + r'\b',
            re.IGNORECASE | re.DOTALL,
        )
        if self_ref_pattern.search(rest[:2000]):
            return f"WITH RECURSIVE {cte_name}{col_list} AS ("
        return m.group(0)

    result = re.sub(
        r'\bWITH\s+(?!RECURSIVE\b)(\w+)(\([^)]*\))?\s+AS\s*\(',
        _check_and_add, sql, flags=re.IGNORECASE,
    )
    return result


def _convert_quoted_column_aliases(sql: str) -> str:
    """T-SQL AS 'ColumnAlias' → PostgreSQL AS "ColumnAlias"."""
    return re.sub(
        r"\bAS\s+'([^']+)'",
        r'AS "\1"',
        sql,
        flags=re.IGNORECASE,
    )


def _strip_tsql_query_options(sql: str) -> str:
    """Remove SQL Server OPTION(...) query hints (MAXRECURSION, RECOMPILE, etc.)."""
    return re.sub(r"\bOPTION\s*\([^)]*\)", "", sql, flags=re.IGNORECASE)


def _convert_select_var_assign(sql: str, params: list[ParamInfo]) -> str:
    """
    SELECT @v1=e1, @v2=e2 FROM t WHERE ... → SELECT e1, e2 INTO v_v1, v_v2 FROM t WHERE ...
    """
    param_names = {p.name.upper() for p in params}

    def _repl(m: re.Match) -> str:  # type: ignore[type-arg]
        col_list = m.group(1).strip()
        from_clause = m.group(2) or ""

        # Check all columns are @var = expr assignments
        col_items = _split_top_level(col_list, ',')
        exprs: list[str] = []
        vars_: list[str] = []

        for item in col_items:
            item = item.strip()
            # Match @VarName = expr
            assign_m = re.match(r'@(\w+)\s*=\s*(.+)', item, re.IGNORECASE | re.DOTALL)
            if not assign_m:
                return m.group(0)  # not all are assignments → leave unchanged
            vname = assign_m.group(1)
            expr = assign_m.group(2).strip()
            prefix = "p_" if vname.upper() in param_names else "v_"
            vars_.append(f"{prefix}{vname}")
            exprs.append(expr)

        expr_list = ', '.join(exprs)
        into_list = ', '.join(vars_)
        from_part = from_clause.strip()
        if from_part:
            return f"SELECT {expr_list} INTO {into_list} {from_part}"
        return f"SELECT {expr_list} INTO {into_list}"

    # Split the SQL into individual statements (separated by ;) and process each
    # We need to match: SELECT col_list FROM|WHERE|; (with all cols being @var=expr)
    # The regex captures column list up to FROM keyword or end-of-statement
    sql = re.sub(
        r'\bSELECT\s+((?:@\w+\s*=\s*[^;]+?(?=\s+FROM\b|\s*;|\s*$)))'
        r'(\s+FROM\b[^;]*)?(?=;|\n|$)',
        _repl, sql, flags=re.IGNORECASE | re.MULTILINE,
    )
    return sql


def _convert_set_var_assign(sql: str, params: list[ParamInfo]) -> str:
    """SET @var = expr → p_var := expr (params) or v_var := expr (locals)."""
    param_names = {p.name.upper() for p in params}

    def _repl(m: re.Match) -> str:  # type: ignore[type-arg]
        vname = m.group(1)
        expr = m.group(2).rstrip(';').strip()
        prefix = "p_" if vname.upper() in param_names else "v_"
        return f"{prefix}{vname} := {expr};"

    return re.sub(
        r'\bSET\s+@(\w+)\s*=\s*(.+?)\s*;',
        _repl, sql, flags=re.IGNORECASE | re.DOTALL,
    )


def _convert_variable_references(sql: str, param_names: set[str]) -> str:
    """
    Replace remaining @VarName references with p_VarName (if param) or v_VarName (if local).
    Does NOT touch @@system_globals (they were handled earlier).
    """

    def _repl(m: re.Match) -> str:  # type: ignore[type-arg]
        vname = m.group(1)
        prefix = "p_" if vname.upper() in param_names else "v_"
        return f"{prefix}{vname}"

    # @var references that are NOT @@globals
    return re.sub(r'(?<!@)@([a-zA-Z_]\w*)', _repl, sql)


def _convert_string_concat(sql: str) -> str:
    """Replace T-SQL string `+` concatenation with PostgreSQL `||`.

    Applies multiple passes to cover the common patterns without touching
    numeric arithmetic (e.g., v_count := v_count + 1).

    Covered patterns (at least one side must be a string literal):
      'str' + 'str'      → 'str' || 'str'
      'str' + word       → 'str' || word
      word   + 'str'     → word  || 'str'
      func() + 'str'     → func() || 'str'   ← Bug-3 fix: ) + 'str' case
      'str'  + func(     → 'str' || func(    ← Bug-3 fix: 'str' + func( case
    """
    # Pass 1: literal + literal
    sql = re.sub(
        r"('[^']*')\s*\+\s*('[^']*')",
        lambda m: f"{m.group(1)} || {m.group(2)}",
        sql,
    )
    # Pass 2: literal + word  (e.g. 'str' + varname  or  'str' + CAST)
    sql = re.sub(
        r"('[^']*')\s*\+\s*(\w)",
        lambda m: f"{m.group(1)} || {m.group(2)}",
        sql,
    )
    # Pass 3: word + literal  (e.g. varname + 'str')
    sql = re.sub(
        r"(\w)\s*\+\s*('[^']*')",
        lambda m: f"{m.group(1)} || {m.group(2)}",
        sql,
    )
    # Pass 4: func-result) + literal  e.g. quote_ident(x) + ' ...'
    sql = re.sub(
        r"(\))\s*\+\s*('[^']*')",
        lambda m: f"{m.group(1)} || {m.group(2)}",
        sql,
    )
    # Pass 5: literal + func-call  e.g. ' ...' + quote_ident(x)
    sql = re.sub(
        r"('[^']*')\s*\+\s*(\()",
        lambda m: f"{m.group(1)} || {m.group(2)}",
        sql,
    )
    # Pass 7: var + var in string-building chains (e.g. v_a + v_b || 'suffix')
    sql = re.sub(
        r"(\bv_\w+)\s*\+\s*(\bv_\w+)\s*\|\|",
        r"\1 || \2 ||",
        sql,
    )
    # Multiline PRINT → RAISE NOTICE: fix ';+ ' artifacts between string literals
    sql = re.sub(r";\s*\+\s*'", " || '", sql)
    return sql


def _convert_money_type_in_declare(sql: str) -> str:
    """Convert SQL Server types to PostgreSQL equivalents throughout the body."""
    sql = re.sub(r'\bMONEY\b', 'NUMERIC', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bSMALLMONEY\b', 'NUMERIC', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bNVARCHAR\s*\(\s*MAX\s*\)', 'TEXT', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bVARCHAR\s*\(\s*MAX\s*\)', 'TEXT', sql, flags=re.IGNORECASE)
    # NVARCHAR(n) / NCHAR(n) in body
    sql = re.sub(r'\bNVARCHAR\s*\(', 'VARCHAR(', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bNCHAR\s*\(', 'CHAR(', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bNTEXT\b', 'TEXT', sql, flags=re.IGNORECASE)
    # DATETIME2(n) / DATETIME2 → TIMESTAMP
    sql = re.sub(r'\bDATETIME2\s*(?:\(\s*\d+\s*\))?', 'TIMESTAMP', sql, flags=re.IGNORECASE)
    sql = re.sub(r'\bSMALLDATETIME\b', 'TIMESTAMP', sql, flags=re.IGNORECASE)
    # IDENTITY(seed, increment) → GENERATED ALWAYS AS IDENTITY
    sql = re.sub(
        r'\bIDENTITY\s*\(\s*\d+\s*,\s*\d+\s*\)',
        'GENERATED ALWAYS AS IDENTITY',
        sql, flags=re.IGNORECASE,
    )
    # SQL_VARIANT → TEXT
    sql = re.sub(r'\bSQL_VARIANT\b', 'TEXT', sql, flags=re.IGNORECASE)
    return sql


def _find_if_body_start(line: str) -> Optional[int]:
    """Return the character index where an embedded body statement starts inside
    a single-line IF/ELSIF-body pattern, or None if the line is a pure condition.

    T-SQL allows: ``IF cond SET @v = expr`` and ``ELSE IF cond SET @v = expr``
    (no BEGIN/END).  After our earlier transforms the SET has become ``:=``,
    giving: ``IF cond v_v := expr`` or ``ELSIF cond v_v := expr``.
    This function finds the index of ``v_v`` so the caller can split the line
    into a proper ``IF/ELSIF cond THEN / body; / END IF;`` block.

    Handles paren-depth tracking and single-quoted string literals to avoid
    false matches inside LIKE patterns or string comparisons.
    """
    upper = line.upper()
    # Support both IF and ELSIF (ELSE IF has already been normalised to ELSIF)
    m = re.match(r'^(?:ELSIF|IF)\s+', upper)
    if not m:
        return None

    pos = m.end()      # first char after "IF "
    depth = 0
    in_string = False
    n = len(line)
    i = pos

    while i < n:
        c = line[i]

        # ── string-literal tracking ────────────────────────────────────
        if c == "'" and not in_string:
            in_string = True
            i += 1
            continue
        if c == "'" and in_string:
            if i + 1 < n and line[i + 1] == "'":  # escaped ''
                i += 2
                continue
            in_string = False
            i += 1
            continue
        if in_string:
            i += 1
            continue

        # ── paren depth ────────────────────────────────────────────────
        if c == '(':
            depth += 1
        elif c == ')':
            depth -= 1

        if depth != 0:
            i += 1
            continue

        # ── detect := (PL/pgSQL assignment) ───────────────────────────
        if line[i:i + 2] == ':=':
            # Scan backwards to find the start of the LHS variable name.
            j = i - 1
            while j >= pos and line[j] in ' \t':     # skip whitespace
                j -= 1
            lhs_end = j
            while j >= pos and (line[j].isalnum() or line[j] == '_'):
                j -= 1                                # skip word chars
            var_start = j + 1
            # Only split when there is a genuine condition before the variable.
            # If var_start == pos the assignment IS the very first token → no condition.
            if var_start > pos and lhs_end >= var_start:
                cond_text = line[pos:var_start].strip()
                if cond_text:
                    return var_start

        # ── detect DML / control keywords that start a body statement ──
        for kw in ('INSERT INTO', 'UPDATE ', 'DELETE FROM', 'DELETE ',
                   'EXECUTE ', 'PERFORM ', 'RAISE ', 'RETURN '):
            klen = len(kw)
            if upper[i:i + klen] == kw and i > pos and line[i - 1] in ' \t\n':
                return i

        i += 1

    return None


def _convert_control_flow(sql: str) -> str:
    """
    Convert T-SQL IF/ELSE/WHILE/BEGIN/END control flow to PL/pgSQL.

    T-SQL:   IF cond BEGIN ... END
    PL/pgSQL: IF cond THEN ... END IF;

    T-SQL:   WHILE cond BEGIN ... END
    PL/pgSQL: WHILE cond LOOP ... END LOOP;

    T-SQL:   ELSE BEGIN ... END
    PL/pgSQL: ELSE ... END IF;  (END IF goes after the ELSE block)

    We use a line-by-line state machine that is simpler than full AST parsing
    but handles the common nesting patterns in real-world SPs.
    """
    # Normalise: ELSE IF → ELSIF
    sql = re.sub(r'\bELSE\s+IF\b', 'ELSIF', sql, flags=re.IGNORECASE)

    lines = sql.split('\n')
    result: list[str] = []
    # stack entry: ('if'|'while'|'begin') → tracks what kind of block opened
    block_stack: list[str] = []

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        upper = stripped.upper()
        indent = re.match(r'^(\s*)', line).group(1)  # type: ignore[union-attr]

        # ── IF condition BEGIN ──────────────────────────────────────────
        if re.match(r'^IF\b.+\bBEGIN\s*$', upper):
            cond = re.sub(r'\bBEGIN\s*$', 'THEN', stripped, flags=re.IGNORECASE)
            result.append(f"{indent}{cond}")
            block_stack.append('if')
            i += 1
            continue

        # ── IF condition (no BEGIN on same line) ───────────────────────
        if re.match(r'^IF\b', upper) and not re.search(r'\bTHEN\b|\bBEGIN\b', upper):
            # Look ahead: if next non-empty line is BEGIN, consume it
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines) and lines[j].strip().upper() == 'BEGIN':
                cond_line = re.sub(r';?\s*$', '', stripped)
                result.append(f"{indent}{cond_line} THEN")
                block_stack.append('if')
                i = j + 1
                continue
            else:
                # Single-statement IF without BEGIN/END.
                cond_line = re.sub(r';?\s*$', '', stripped)

                # Bug-1 fix: detect embedded body statement on the same line.
                # e.g. "IF p_x IS NOT NULL v_Sql := v_Sql || ' WHERE ' || p_x"
                # → split into proper IF/THEN/body/END IF; block.
                split_pos = _find_if_body_start(cond_line)
                if split_pos is not None:
                    cond_part = cond_line[:split_pos].rstrip()
                    body_part = cond_line[split_pos:].strip()
                    if body_part and not body_part.endswith(';'):
                        body_part += ';'
                    result.append(f"{indent}{cond_part} THEN")
                    if body_part:
                        result.append(f"{indent}    {body_part}")
                    result.append(f"{indent}END IF;")
                    i += 1
                    continue

                result.append(f"{indent}{cond_line} THEN")
                block_stack.append('if_single')
                i += 1
                continue

        # ── ELSIF condition BEGIN ──────────────────────────────────────
        if re.match(r'^ELSIF\b.+\bBEGIN\s*$', upper):
            cond = re.sub(r'\bBEGIN\s*$', 'THEN', stripped, flags=re.IGNORECASE)
            result.append(f"{indent}{cond}")
            if block_stack and block_stack[-1] in ('if', 'if_single'):
                block_stack.pop()
            block_stack.append('if')
            i += 1
            continue

        # ── ELSIF condition (no BEGIN on same line) ────────────────────
        if re.match(r'^ELSIF\b', upper) and not re.search(r'\bTHEN\b|\bBEGIN\b', upper):
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines) and lines[j].strip().upper() == 'BEGIN':
                cond_line = re.sub(r';?\s*$', '', stripped)
                result.append(f"{indent}{cond_line} THEN")
                if block_stack and block_stack[-1] in ('if', 'if_single'):
                    block_stack.pop()
                block_stack.append('if')
                i = j + 1
                continue
            else:
                # Single-statement ELSIF without BEGIN/END.
                cond_line = re.sub(r';?\s*$', '', stripped)
                split_pos = _find_if_body_start(cond_line)
                if split_pos is not None:
                    cond_part = cond_line[:split_pos].rstrip()
                    body_part = cond_line[split_pos:].strip()
                    if body_part and not body_part.endswith(';'):
                        body_part += ';'
                    result.append(f"{indent}{cond_part} THEN")
                    if body_part:
                        result.append(f"{indent}    {body_part}")
                    result.append(f"{indent}END IF;")
                else:
                    result.append(f"{indent}{cond_line} THEN")
                    if block_stack and block_stack[-1] in ('if', 'if_single'):
                        block_stack.pop()
                    block_stack.append('if_single')
                i += 1
                continue

        # ── ELSE BEGIN ─────────────────────────────────────────────────
        if re.match(r'^ELSE\s+BEGIN\s*$', upper) or upper == 'ELSE BEGIN':
            result.append(f"{indent}ELSE")
            block_stack.append('else')
            i += 1
            continue

        # ── Standalone BEGIN ───────────────────────────────────────────
        if upper == 'BEGIN' or upper == 'BEGIN;':
            # In PL/pgSQL we don't need bare BEGIN (already inside BEGIN...END)
            # Only emit if it's a sub-block for a new exception handler
            if block_stack and block_stack[-1] in ('if', 'if_single', 'while', 'else'):
                pass  # absorbed – the BEGIN was part of the if/while structure
            else:
                block_stack.append('block')
                result.append(line)
            i += 1
            continue

        # ── WHILE cond BEGIN ───────────────────────────────────────────
        if re.match(r'^WHILE\b.+\bBEGIN\s*$', upper):
            cond = re.sub(r'\bBEGIN\s*$', 'LOOP', stripped, flags=re.IGNORECASE)
            result.append(f"{indent}{cond}")
            block_stack.append('while')
            i += 1
            continue

        if re.match(r'^WHILE\b', upper) and not re.search(r'\bLOOP\b|\bBEGIN\b', upper):
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines) and lines[j].strip().upper() == 'BEGIN':
                cond_line = re.sub(r';?\s*$', '', stripped)
                result.append(f"{indent}{cond_line} LOOP")
                block_stack.append('while')
                i = j + 1
                continue

        # ── END; / END ─────────────────────────────────────────────────
        if re.match(r'^END\s*;?\s*$', upper):
            if block_stack:
                ctx = block_stack.pop()
                if ctx in ('if', 'if_single', 'else'):
                    result.append(f"{indent}END IF;")
                elif ctx == 'while':
                    result.append(f"{indent}END LOOP;")
                elif ctx == 'block':
                    result.append(line)
                # else: absorbed
            else:
                result.append(line)
            i += 1
            continue

        # For single-statement IF blocks, close after one statement
        if block_stack and block_stack[-1] == 'if_single' and stripped and not re.match(
            r'^(ELSE|ELSIF|END)\b', upper
        ):
            result.append(line)
            if not re.match(r'^(IF|ELSIF|ELSE|BEGIN|END|WHILE)\b', upper):
                block_stack.pop()
                # If next line is not ELSE/ELSIF, add END IF
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j >= len(lines) or not re.match(
                    r'^\s*(ELSE|ELSIF)\b', lines[j], re.IGNORECASE
                ):
                    result.append(f"{indent}END IF;")
            i += 1
            continue

        result.append(line)
        i += 1

    return '\n'.join(result)


def _count_top_level_selects(sql: str) -> int:
    """
    Count SELECT statements that are at the top level (not inside CTEs or subqueries).
    Heuristic: find SELECTs not preceded by WITH/UNION/JOIN/FROM or inside parens.
    """
    upper = sql.upper()
    # Strip CTE definitions by finding WITH...AS(...) blocks and removing them
    # Simple approach: count semicolons separating statements, each ending in SELECT
    # For now: split by ';' and count parts that contain a top-level SELECT
    stmts = [s.strip() for s in upper.split(';') if s.strip()]
    count = 0
    for stmt in stmts:
        # A statement is a top-level SELECT if it starts with SELECT (optionally preceded by WITH)
        if re.match(r'^(?:WITH\b|SELECT\b)', stmt, re.IGNORECASE):
            count += 1
        elif re.match(r'^RETURN\s+QUERY\s+(?:EXECUTE\s+)?SELECT\b', stmt, re.IGNORECASE):
            count += 1
    return count


# ---------------------------------------------------------------------------
# Fix 3.7 — ISNUMERIC conversion
# ---------------------------------------------------------------------------

def _convert_isnumeric(sql: str) -> str:
    """Fix 3.7: ISNUMERIC(expr) → regex-based numeric check returning 0/1.

    PostgreSQL has no built-in ISNUMERIC. Replace with a regex cast expression.
    """
    def _repl(m: re.Match) -> str:  # type: ignore[type-arg]
        expr = m.group(1).strip()
        return (
            f"(({expr}) ~ "
            r"'^[+-]?([0-9]*\.)?[0-9]+([eE][+-]?[0-9]+)?$'"
            f")::INT /* is_numeric */"
        )
    return re.sub(r'\bISNUMERIC\s*\(([^)]+)\)', _repl, sql, flags=re.IGNORECASE)


# ---------------------------------------------------------------------------
# Fix 3.8 — FORMAT() function conversion
# ---------------------------------------------------------------------------

_FORMAT_MAP: dict[str, str] = {
    "yyyy-MM-dd": "YYYY-MM-DD",
    "yyyy/MM/dd": "YYYY/MM/DD",
    "dd/MM/yyyy": "DD/MM/YYYY",
    "MM/dd/yyyy": "MM/DD/YYYY",
    "HH:mm:ss": "HH24:MI:SS",
    "hh:mm:ss tt": "HH12:MI:SS AM",
    "yyyy-MM-dd HH:mm:ss": "YYYY-MM-DD HH24:MI:SS",
    "d": "FMDD",
    "D": "FMDay, DD Month YYYY",
    "N0": "FM999,999,999,990",
    "N2": "FM999,999,999,990.00",
    "N4": "FM999,999,999,990.0000",
    "C2": "L999,999,990.00",
    "P2": "FM990.00%",
    "G": "",   # general — no direct mapping; fall through
}


def _convert_format_function(sql: str) -> str:
    """Fix 3.8: FORMAT(value, format_string [, culture]) → TO_CHAR(value, pg_format).

    The culture argument (3rd arg) has no PostgreSQL equivalent and is dropped.
    Format strings are translated via a lookup table; unknown formats are passed
    through with a comment so the developer sees what needs manual review.

    Uses a balanced-paren scan so nested function calls like FORMAT(GETDATE(), ...)
    are handled correctly.
    """
    result = []
    i = 0
    pattern = re.compile(r'\bFORMAT\s*\(', re.IGNORECASE)

    while i < len(sql):
        m = pattern.search(sql, i)
        if not m:
            result.append(sql[i:])
            break

        # Append text before the match
        result.append(sql[i:m.start()])

        # Find the matching closing paren using depth counting
        depth = 1
        j = m.end()
        while j < len(sql) and depth > 0:
            if sql[j] == '(':
                depth += 1
            elif sql[j] == ')':
                depth -= 1
            j += 1

        inner = sql[m.end():j - 1]  # content between FORMAT( and its closing )
        args = _split_top_level(inner, ',')

        if len(args) < 2:
            result.append(sql[m.start():j])
        else:
            value = args[0].strip()
            fmt_raw = args[1].strip().strip("'\"")
            # args[2] is culture — deliberately dropped (no PG equivalent)
            pg_fmt = _FORMAT_MAP.get(fmt_raw)
            if pg_fmt is None:
                result.append(f"TO_CHAR({value}, '{fmt_raw}') /* TODO: verify FORMAT→TO_CHAR mapping */")
            elif not pg_fmt:
                result.append(f"({value})::TEXT")
            else:
                result.append(f"TO_CHAR({value}, '{pg_fmt}')")

        i = j

    return "".join(result)


# ---------------------------------------------------------------------------
# Fix 3.9 — FOR XML PATH / OPENXML conversion
# ---------------------------------------------------------------------------

def _convert_for_xml_path(sql: str) -> str:
    """Fix 3.9: Convert T-SQL XML string-aggregation patterns to PostgreSQL.

    Handles:
    - STUFF((SELECT sep + col FROM t FOR XML PATH('')), 1, N, '')
      → (SELECT STRING_AGG(col, sep) FROM t)
    - Bare FOR XML PATH → TODO comment
    - OPENXML → TODO comment
    """
    # Pattern: STUFF((SELECT 'sep' + col FROM tbl FOR XML PATH('')), 1, N, '')
    _stuff_xml_re = re.compile(
        r"STUFF\s*\(\s*\(\s*SELECT\s+(.+?)\s+FROM\s+(.+?)\s+FOR\s+XML\s+PATH\s*\(\s*''\s*\)\s*\)"
        r"\s*,\s*1\s*,\s*(\d+)\s*,\s*''\s*\)",
        re.IGNORECASE | re.DOTALL,
    )

    def _repl_stuff(m: re.Match) -> str:  # type: ignore[type-arg]
        select_expr = m.group(1).strip()
        from_clause = m.group(2).strip()
        sep_m = re.match(r"N?'([^']+)'\s*(?:\+|\|\|)\s*(.+)", select_expr, re.IGNORECASE)
        if sep_m:
            sep = sep_m.group(1)
            col = sep_m.group(2).strip()
            return f"(SELECT STRING_AGG({col}, '{sep}') FROM {from_clause})"
        return f"(SELECT STRING_AGG({select_expr}, '') FROM {from_clause})"

    result = _stuff_xml_re.sub(_repl_stuff, sql)

    if re.search(r"\bFOR\s+XML\b", result, re.IGNORECASE):
        result = re.sub(
            r"\bFOR\s+XML\b(?:\s+(?:PATH|AUTO|RAW|EXPLICIT))?(?:\s*\([^)]*\))?",
            "/* MANUAL REVIEW: convert XML PATH using STRING_AGG, xmlagg, xmlelement */",
            result,
            flags=re.IGNORECASE,
        )

    # OPENXML(...) → TODO comment
    result = re.sub(
        r'\bOPENXML\s*\([^)]*\)',
        "/* TODO: OPENXML not converted — use xpath() or jsonb functions */",
        result,
        flags=re.IGNORECASE,
    )

    return result


# ---------------------------------------------------------------------------
