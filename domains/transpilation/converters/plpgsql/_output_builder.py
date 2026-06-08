"""
Module: domains/transpilation/converters/plpgsql/_output_builder.py
Purpose: TsqlToPlpgsqlConverter — the top-level orchestrator that parses a
         complete T-SQL stored procedure, transforms its body, then emits a
         valid ``CREATE OR REPLACE PROCEDURE/FUNCTION`` PL/pgSQL block.

         This module also houses the pgFormatter-style SQL output formatter
         (``format_plpgsql``) that makes the generated code readable.

Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import re

try:
    import sqlglot
    _SQLGLOT_AVAILABLE = True
except ImportError:  # pragma: no cover
    _SQLGLOT_AVAILABLE = False

from domains.transpilation.converters.plpgsql._models import (
    HeaderInfo,
    ParamInfo,
    SprocType,
)
from domains.parsing.tsql_parse_unblocker import TsqlParseUnblocker
from domains.transpilation.converters.plpgsql._type_mapper import TsqlTypeMapper
from domains.transpilation.converters.plpgsql._header_parser import TsqlHeaderParser
from domains.transpilation.converters.plpgsql._body_transforms import (
    TsqlBodyConverter,
    _count_top_level_selects,
)
from domains.transpilation.source_preamble import attach_source_preamble, extract_source_preamble


# ---------------------------------------------------------------------------
# pgFormatter-style SQL output formatter
# ---------------------------------------------------------------------------

# SQL statement keywords that trigger sqlglot pretty-printing when they start
# a (possibly RETURN QUERY-prefixed) line and the line is long.
_SQL_STMT_PREFIXES = (
    "SELECT ", "INSERT ", "UPDATE ", "DELETE ", "WITH ",
)

# Lines shorter than this are left as-is (formatting adds noise for short stmts)
_FORMAT_MIN_LENGTH = 80


def _format_sql_stmt(stmt: str, base_indent: str) -> str:
    """Pretty-print a single SQL statement using sqlglot.

    Returns the formatted string on success, or the original *stmt* unchanged
    on parse failure (so the caller never loses content).
    """
    if not _SQLGLOT_AVAILABLE:
        return stmt

    # Strip RETURN QUERY prefix — sqlglot can't parse PL/pgSQL keywords
    rq_match = re.match(r'^(\s*)(RETURN\s+QUERY\s+)', stmt, re.IGNORECASE)
    prefix_str = ""
    sql_part = stmt
    if rq_match:
        prefix_str = rq_match.group(2)   # "RETURN QUERY "
        sql_part = stmt[rq_match.end():]

    try:
        parsed = sqlglot.parse_one(sql_part.strip(), dialect="postgres")
        pretty = parsed.sql(dialect="postgres", pretty=True)
    except Exception:
        return stmt  # parse failed — return unchanged

    # Re-attach the RETURN QUERY prefix to the first line and indent all lines
    lines_out: list[str] = []
    for idx, line in enumerate(pretty.splitlines()):
        if idx == 0:
            lines_out.append(f"{base_indent}{prefix_str}{line}")
        else:
            lines_out.append(f"{base_indent}  {line}" if line.strip() else "")
    return "\n".join(lines_out)


def format_plpgsql(sql: str) -> str:
    """Apply pgFormatter-style formatting to a generated PL/pgSQL block.

    Formatting rules (matching pgFormatter v5.5 conventions):
    - SQL keywords uppercase (enforced by sqlglot)
    - 4-space indentation per block level (maintained from generator)
    - SELECT column lists: one column per line when statement exceeds 80 chars
    - ``AND``/``OR`` on new lines aligned with ``WHERE`` (sqlglot handles this)
    - ``DECLARE`` block: one declaration per line (already done by generator)
    - No consecutive blank lines

    The function is conservative: if sqlglot fails to parse a statement the
    original text is preserved unchanged, so no content is ever lost.
    """
    result_lines: list[str] = []
    prev_blank = False

    for line in sql.splitlines():
        stripped = line.strip()

        # Collapse consecutive blank lines to one
        if not stripped:
            if not prev_blank:
                result_lines.append("")
            prev_blank = True
            continue
        prev_blank = False

        # Detect the leading indent of this line
        indent_match = re.match(r'^(\s*)', line)
        indent = indent_match.group(1) if indent_match else ""

        # Attempt sqlglot formatting only for COMPLETE single-line SQL statements
        # (must start with a SQL keyword AND end with ';' on the same line).
        # Multi-line SQL is left untouched to avoid consuming continuation lines.
        upper = stripped.upper()
        is_complete_sql = (
            stripped.endswith(';')
            and len(stripped) >= _FORMAT_MIN_LENGTH
            and any(
                upper.startswith(p) or upper.startswith("RETURN QUERY " + p)
                for p in _SQL_STMT_PREFIXES
            )
        )
        if is_complete_sql:
            formatted = _format_sql_stmt(line, indent)
            result_lines.append(formatted)
            continue

        result_lines.append(line)

    # Remove trailing blank lines
    while result_lines and not result_lines[-1].strip():
        result_lines.pop()

    return "\n".join(result_lines)


# ---------------------------------------------------------------------------
# TsqlToPlpgsqlConverter  (main entry point)
# ---------------------------------------------------------------------------

class TsqlToPlpgsqlConverter:
    """
    Converts a complete T-SQL stored procedure SQL string to PL/pgSQL.

    Usage::

        result = TsqlToPlpgsqlConverter().convert(tsql_sql)
    """

    def convert(self, sql: str) -> str:
        """Convert a T-SQL stored procedure / function to PL/pgSQL."""
        comment_preamble, sql_without_preamble = extract_source_preamble(sql)
        needs_aggressive = bool(
            re.search(r"\bGOTO\b", sql_without_preamble, re.IGNORECASE)
            or re.search(r"\bsp_executesql\b", sql_without_preamble, re.IGNORECASE)
        )
        unblock = TsqlParseUnblocker.apply(
            sql_without_preamble,
            aggressive=needs_aggressive,
        )
        sproc_sql = self._extract_sproc_statement(unblock.sql)
        info = TsqlHeaderParser.parse(sproc_sql)

        # Collect CREATE TYPE definitions from preamble (for TVP support comments)
        type_defs = self._extract_type_definitions(sql)

        # Pattern preprocess (OUTPUT → RETURNING, NOLOCK, etc.) then body transforms
        from domains.transpilation.tsql_pattern_converter import TsqlPatternConverter

        pattern_pre = TsqlPatternConverter().preprocess(info.body)
        converted_body = TsqlBodyConverter.convert(pattern_pre.sql, info.parameters)
        pattern_post = TsqlPatternConverter().postprocess(converted_body)
        converted_body = pattern_post.sql

        # Determine output type
        has_output_params = any(p.is_output for p in info.parameters)
        sproc_type = self.detect_sproc_type(converted_body, has_output_params)

        # Build the PG object
        # Prepend CREATE TYPE conversions (TVP definitions) if present
        type_preamble = self._build_type_preamble(type_defs)
        result = self._build_procedure(info, converted_body) if sproc_type == SprocType.PROCEDURE \
            else self._build_function(info, converted_body)
        # Apply pgFormatter-style formatting to the final output
        result = format_plpgsql(result)
        if type_preamble:
            result = attach_source_preamble(type_preamble, result)
        return attach_source_preamble(comment_preamble, result)

    @staticmethod
    def _build_type_preamble(type_defs: list[str]) -> str:
        """Convert CREATE TYPE ... AS TABLE definitions to PostgreSQL composite types."""
        if not type_defs:
            return ""
        lines: list[str] = []
        for td in type_defs:
            # Add as a comment for manual review since PG composite types work differently
            lines.append(
                f"-- ⚠️ TODO: Convert TVP type to PostgreSQL composite type:\n"
                f"-- {td.replace(chr(10), ' ')}\n"
            )
        return "\n".join(lines) + "\n"

    @staticmethod
    def detect_sproc_type(body: str, has_output_params: bool) -> SprocType:
        """
        Determine whether to emit PROCEDURE or FUNCTION.

        Rules:
        - If there are OUTPUT params → PROCEDURE (INOUT params)
        - If body has a SELECT that returns data (no DML or DML + SELECT) → FUNCTION
        - If body is pure DML (INSERT/UPDATE/DELETE) without SELECT result → PROCEDURE
        """
        upper = body.upper()

        if has_output_params:
            return SprocType.PROCEDURE

        has_select = bool(re.search(r'\bSELECT\b', upper))
        has_dml = bool(re.search(r'\b(?:INSERT|UPDATE|DELETE|MERGE)\b', upper))
        has_return_query = bool(re.search(r'\bRETURN\s+QUERY\b', upper))

        if has_return_query or (has_select and not has_dml):
            return SprocType.FUNCTION

        if has_select and has_dml:
            return SprocType.FUNCTION  # default: function with SETOF/TABLE

        # Pure DML or empty body
        return SprocType.PROCEDURE

    def _build_procedure(self, info: HeaderInfo, body: str) -> str:
        """Build a CREATE OR REPLACE PROCEDURE … PL/pgSQL block."""
        param_decls = self._format_params(info.parameters)
        declare_vars = self._collect_declare_vars(body, info.parameters)
        body_clean = self._strip_declare_from_body(body)

        lines = [f"CREATE OR REPLACE PROCEDURE {info.schema}.{info.name}("]
        if param_decls:
            lines.append(f"    {param_decls}")
        lines.append(")")
        lines.append("LANGUAGE plpgsql")
        lines.append("AS $$")
        if declare_vars:
            lines.append("DECLARE")
            for v in declare_vars:
                lines.append(f"    {v}")
        lines.append("BEGIN")
        for line in body_clean.splitlines():
            lines.append(f"    {line}" if line.strip() else "")
        lines.append("END;")
        lines.append("$$;")
        return "\n".join(lines)

    def _build_function(self, info: HeaderInfo, body: str) -> str:
        """Build a CREATE OR REPLACE FUNCTION … PL/pgSQL block."""
        param_decls = self._format_params(info.parameters)
        declare_vars = self._collect_declare_vars(body, info.parameters)
        body_clean = self._strip_declare_from_body(body)

        # Determine RETURNS clause
        # Count only top-level SELECT statements (not those inside CTEs/subqueries)
        # by looking for SELECT that starts a statement (after ; or at line start outside parens)
        top_level_selects = _count_top_level_selects(body_clean)
        has_procedural = bool(
            re.search(
                r'\b(IF|LOOP|WHILE|BEGIN|EXCEPTION|DECLARE|RETURN\s+QUERY|GET\s+DIAGNOSTICS)\b',
                body.upper(),
            )
        )
        has_dml = bool(re.search(r'\b(?:INSERT|UPDATE|DELETE)\b', body.upper()))

        if top_level_selects > 1:
            returns_clause = "RETURNS SETOF JSON"
        else:
            returns_clause = "RETURNS SETOF RECORD"

        use_language_sql = not has_procedural and not has_dml and not declare_vars

        lines = [f"CREATE OR REPLACE FUNCTION {info.schema}.{info.name}("]
        if param_decls:
            lines.append(f"    {param_decls}")
        lines.append(")")
        lines.append(returns_clause)

        if use_language_sql:
            lines.append("LANGUAGE sql")
            lines.append("AS $$")
            for line in body_clean.splitlines():
                lines.append(f"    {line}" if line.strip() else "")
            lines.append("$$;")
        else:
            lines.append("LANGUAGE plpgsql")
            lines.append("AS $$")
            if declare_vars:
                lines.append("DECLARE")
                for v in declare_vars:
                    lines.append(f"    {v}")
            lines.append("BEGIN")
            # Wrap SELECTs with RETURN QUERY if not already present
            body_wrapped = self._add_return_query(body_clean)
            for line in body_wrapped.splitlines():
                lines.append(f"    {line}" if line.strip() else "")
            lines.append("END;")
            lines.append("$$;")

        return "\n".join(lines)

    @staticmethod
    def _add_return_query(body: str) -> str:
        """Prepend RETURN QUERY to bare SELECT statements.

        Skips SELECTs that are:
        - Part of a cursor declaration (SELECT immediately follows CURSOR FOR)
        - Inside an INSERT ... SELECT (previous non-blank line is INSERT or column list)
        - Already wrapped with RETURN QUERY
        """
        lines = body.splitlines()
        result: list[str] = []
        in_cursor_decl = False
        in_insert = False  # track INSERT ... SELECT context

        for line in lines:
            stripped = line.strip()
            upper = stripped.upper()

            # Track INSERT context: a line starting with INSERT sets the flag;
            # any line that is NOT a SELECT/FROM/WHERE/ON/VALUES continuation clears it.
            if re.match(r'\bINSERT\b', upper):
                in_insert = True
            elif stripped and not re.match(
                r'^(SELECT|FROM|WHERE|ON\b|VALUES|JOIN|LEFT|RIGHT|INNER|OUTER|FULL|GROUP|ORDER|HAVING|LIMIT|UNION|ON\s+CONFLICT)',
                upper,
            ):
                in_insert = False

            # Detect cursor declaration line
            if re.search(r'\bCURSOR\s+FOR\s*$', line, re.IGNORECASE):
                in_cursor_decl = True
                result.append(line)
                continue
            # A SELECT on the first content line after CURSOR FOR is the cursor body
            if in_cursor_decl and re.match(r'^\s*SELECT\b', line, re.IGNORECASE):
                result.append(line)
                in_cursor_decl = False
                continue
            in_cursor_decl = False

            # Add RETURN QUERY before bare SELECTs unless in a skip context
            if (
                re.match(r'^(\s*)SELECT\b(?!\s+INTO\b)', line, re.IGNORECASE)
                and not re.match(r'^\s*RETURN\s+QUERY\b', line, re.IGNORECASE)
                and not in_insert
            ):
                m = re.match(r'^(\s*)(SELECT\b)', line, re.IGNORECASE)
                if m:
                    line = f"{m.group(1)}RETURN QUERY {line[m.start(2):]}"
            result.append(line)
        return '\n'.join(result)

    @staticmethod
    def _format_params(params: list[ParamInfo]) -> str:
        if not params:
            return ""
        return ",\n    ".join(p.pg_declaration for p in params)

    @staticmethod
    def _collect_declare_vars(body: str, params: list[ParamInfo]) -> list[str]:
        """
        Extract DECLARE @var / DECLARE v_var lines from body and convert to
        PL/pgSQL DECLARE block entries.

        Handles both the original @var form (T-SQL) and the already-converted v_var
        form produced when _expand_multi_var_declare runs before _convert_variable_references.
        """
        param_names_upper = {p.name.upper() for p in params}
        declares: list[str] = []
        seen: set[str] = set()

        # Pattern 1: still has @var (unprocessed or partially processed)
        for m in re.finditer(
            r'\bDECLARE\s+@(\w+)\s+([\w\s\(\),]+?)(?:\s*=\s*([^;,\n]+))?\s*;',
            body, re.IGNORECASE,
        ):
            vname = m.group(1)
            if vname.upper() in param_names_upper or vname.upper() in seen:
                continue
            raw_type = m.group(2).strip()
            default_raw = m.group(3)
            if 'TABLE' in raw_type.upper():
                continue
            seen.add(vname.upper())
            pg_type = TsqlTypeMapper.map(raw_type)
            pg_default = TsqlTypeMapper.map_default(default_raw, raw_type)
            if pg_default:
                declares.append(f"v_{vname} {pg_type} := {pg_default};")
            else:
                declares.append(f"v_{vname} {pg_type};")

        # Pattern 2: already renamed to v_var (after _expand_multi_var_declare +
        #            _convert_variable_references ran before _collect_declare_vars)
        for m in re.finditer(
            r'\bDECLARE\s+(v_\w+)\s+([\w\s\(\),]+?)(?:\s*(?::=|=)\s*([^;,\n]+))?\s*;',
            body, re.IGNORECASE,
        ):
            pg_var = m.group(1)          # already "v_something"
            vname_key = pg_var.upper()
            if vname_key in seen:
                continue
            raw_type = m.group(2).strip()
            default_raw = m.group(3)
            if 'TABLE' in raw_type.upper():
                continue
            seen.add(vname_key)
            pg_type = TsqlTypeMapper.map(raw_type)
            pg_default = TsqlTypeMapper.map_default(default_raw, raw_type) if default_raw else None
            if pg_default:
                declares.append(f"{pg_var} {pg_type} := {pg_default};")
            else:
                declares.append(f"{pg_var} {pg_type};")

        return declares

    @staticmethod
    def _strip_declare_from_body(body: str) -> str:
        """Remove DECLARE @var / DECLARE v_var lines from body (moved to DECLARE block)."""
        # Remove @var form
        body = re.sub(
            r'\bDECLARE\s+@\w+\s+[\w\s\(\),]+?\s*(?:=\s*[^;,\n]+)?\s*;',
            '', body, flags=re.IGNORECASE,
        )
        # Remove v_var form (produced by _expand_multi_var_declare after rename)
        body = re.sub(
            r'\bDECLARE\s+v_\w+\s+[\w\s\(\),]+?\s*(?:(?::=|=)\s*[^;,\n]+)?\s*;',
            '', body, flags=re.IGNORECASE,
        )
        return body.strip()

    @staticmethod
    def _extract_sproc_statement(sql: str) -> str:
        """
        When a file contains multiple GO-separated statements, extract only
        the CREATE PROCEDURE/FUNCTION block.  If only one statement exists,
        return the whole input.
        """
        # Split on GO at start of line (T-SQL batch separator)
        batches = re.split(r'^\s*GO\s*$', sql, flags=re.IGNORECASE | re.MULTILINE)

        for batch in batches:
            stripped = batch.strip()
            if re.search(r'\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:PROCEDURE|PROC|FUNCTION)\b',
                         stripped, re.IGNORECASE):
                return stripped

        # No explicit GO splitting found; return as-is
        return sql

    @staticmethod
    def _extract_type_definitions(sql: str) -> list[str]:
        """Extract CREATE TYPE ... AS TABLE definitions from the SQL preamble."""
        return re.findall(
            r'CREATE\s+TYPE\s+[\w\.\[\]]+\s+AS\s+TABLE\s*\([^)]+\)',
            sql, re.IGNORECASE | re.DOTALL,
        )
