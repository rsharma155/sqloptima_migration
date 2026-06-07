"""
Module: domains/transpilation/tsql_pattern_converter.py
Purpose: Handles T-SQL construct conversions that require multi-line pattern
         matching: NOLOCK hints, MERGE upserts, FOR XML PATH, MAXRECURSION,
         and global temporary table references (##).
         All transformations annotate unsupported constructs with
         ⚠️ MANUAL REVIEW comments in the output SQL rather than silently
         dropping or corrupting them.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class PatternConversionResult:
    """Outcome of applying all pattern conversions to a SQL string."""

    sql: str
    warnings: list[str] = field(default_factory=list)
    manual_review_required: bool = False


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


class TsqlPatternConverter:
    """Applies T-SQL pattern rewrites that go beyond simple function mapping.

    The conversions are split into two phases to avoid interfering with SQLGlot:

    * :meth:`preprocess` — must run **before** SQLGlot transpilation.  Handles
      NOLOCK hints and ``##`` global temp-table renames, which need to be
      normalised so SQLGlot can parse the SQL correctly.

    * :meth:`postprocess` — must run **after** SQLGlot transpilation.  Handles
      FOR XML/JSON PATH, MAXRECURSION, and MERGE.  If SQLGlot already converted
      one of these (e.g. ``STUFF(…FOR XML PATH…)`` → ``OVERLAY(…)``), no
      annotation is added because the pattern is no longer present in the output.

    :meth:`convert` runs both phases in sequence (used for standalone testing).
    """

    def preprocess(self, sql: str) -> PatternConversionResult:
        """Apply patterns that must run *before* SQLGlot transpilation."""
        warnings: list[str] = []

        sql, w = _remove_nolock(sql)
        warnings.extend(w)

        sql, w = _flag_global_temp_tables(sql)
        warnings.extend(w)

        from domains.transpilation.converters.plpgsql._body_transforms import _convert_for_xml_path

        before_xml = sql
        sql = _convert_for_xml_path(sql)
        if sql != before_xml:
            if re.search(r"\bSTRING_AGG\b", sql, re.IGNORECASE):
                warnings.append(
                    "FOR XML PATH (STUFF pattern): converted to STRING_AGG — verify separator and null handling"
                )
            else:
                warnings.append(
                    "FOR XML: MANUAL REVIEW REQUIRED — rewrite using STRING_AGG, xmlagg, or xmlelement"
                )

        sql, w = _convert_raiserror(sql)
        warnings.extend(w)

        sql, w = _convert_output_clause(sql)
        warnings.extend(w)

        manual = any("MANUAL REVIEW" in warning.upper() for warning in warnings)
        return PatternConversionResult(sql=sql, warnings=warnings, manual_review_required=manual)

    def postprocess(self, sql: str) -> PatternConversionResult:
        """Apply patterns that must run *after* SQLGlot transpilation."""
        warnings: list[str] = []

        sql, w = _convert_for_xml_path(sql)
        warnings.extend(w)

        sql, w = _convert_maxrecursion(sql)
        warnings.extend(w)

        sql, w = _convert_merge(sql)
        warnings.extend(w)

        manual = any("MANUAL REVIEW" in warning.upper() for warning in warnings)
        return PatternConversionResult(sql=sql, warnings=warnings, manual_review_required=manual)

    def convert(self, sql: str) -> PatternConversionResult:
        """Apply all pattern conversions (pre + post) — used standalone/for tests."""
        pre = self.preprocess(sql)
        post = self.postprocess(pre.sql)
        all_warnings = pre.warnings + post.warnings
        return PatternConversionResult(
            sql=post.sql,
            warnings=all_warnings,
            manual_review_required=pre.manual_review_required or post.manual_review_required,
        )


# ---------------------------------------------------------------------------
# NOLOCK hint removal
# ---------------------------------------------------------------------------

# Matches: WITH (NOLOCK), WITH(NOLOCK), NOLOCK standalone hint
_NOLOCK_PATTERN = re.compile(
    r"\bWITH\s*\(\s*NOLOCK\s*\)",
    re.IGNORECASE,
)

# Also handle bare table hints such as (NOLOCK) without WITH
_BARE_NOLOCK_PATTERN = re.compile(
    r"\(\s*NOLOCK\s*\)",
    re.IGNORECASE,
)

_NOLOCK_COMMENT = (
    "/* ⚠️ NOLOCK hint removed — "
    "PostgreSQL uses READ COMMITTED isolation by default; "
    "verify isolation requirements */"
)


def _remove_nolock(sql: str) -> tuple[str, list[str]]:
    warnings: list[str] = []
    count = len(_NOLOCK_PATTERN.findall(sql))
    if count:
        sql = _NOLOCK_PATTERN.sub(_NOLOCK_COMMENT, sql)
        warnings.append(
            f"NOLOCK: {count} WITH (NOLOCK) hint(s) replaced with READ COMMITTED comment — "
            "verify isolation level requirements manually"
        )
    # Catch any remaining bare (NOLOCK) that was not preceded by WITH
    bare_count = len(_BARE_NOLOCK_PATTERN.findall(sql))
    if bare_count:
        sql = _BARE_NOLOCK_PATTERN.sub(_NOLOCK_COMMENT, sql)
        warnings.append(
            f"NOLOCK: {bare_count} bare (NOLOCK) hint(s) removed — see above"
        )
    return sql, warnings


# ---------------------------------------------------------------------------
# FOR XML PATH conversion
# ---------------------------------------------------------------------------

# Matches: FOR XML PATH('...') or FOR XML PATH, including AUTO/RAW/EXPLICIT
_FOR_XML_PATTERN = re.compile(
    r"\bFOR\s+XML\s+(PATH|AUTO|RAW|EXPLICIT)(\s*\([^)]*\))?",
    re.IGNORECASE,
)

_FOR_XML_COMMENT = (
    "/* ⚠️ MANUAL REVIEW REQUIRED: FOR XML {mode} — "
    "rewrite using STRING_AGG(), jsonb_agg(), or xmlelement() in PostgreSQL */"
)

_FOR_JSON_PATTERN = re.compile(
    r"\bFOR\s+JSON\s+(PATH|AUTO)(\s*\([^)]*\))?",
    re.IGNORECASE,
)

_FOR_JSON_COMMENT = (
    "/* ⚠️ MANUAL REVIEW REQUIRED: FOR JSON {mode} — "
    "rewrite using json_agg() or jsonb_build_object() in PostgreSQL */"
)


def _convert_for_xml_path(sql: str) -> tuple[str, list[str]]:
    warnings: list[str] = []

    def _replace_xml(m: re.Match) -> str:  # type: ignore[type-arg]
        mode = m.group(1).upper()
        warnings.append(
            f"FOR XML {mode}: convert to STRING_AGG/jsonb_agg; "
            "⚠️ MANUAL REVIEW REQUIRED"
        )
        return _FOR_XML_COMMENT.format(mode=mode)

    def _replace_json(m: re.Match) -> str:  # type: ignore[type-arg]
        mode = m.group(1).upper()
        warnings.append(
            f"FOR JSON {mode}: convert to json_agg/jsonb_build_object; "
            "⚠️ MANUAL REVIEW REQUIRED"
        )
        return _FOR_JSON_COMMENT.format(mode=mode)

    sql = _FOR_XML_PATTERN.sub(_replace_xml, sql)
    sql = _FOR_JSON_PATTERN.sub(_replace_json, sql)
    return sql, warnings


# ---------------------------------------------------------------------------
# MAXRECURSION hint
# ---------------------------------------------------------------------------

_MAXRECURSION_PATTERN = re.compile(
    r"\bOPTION\s*\(\s*MAXRECURSION\s+(\d+)\s*\)",
    re.IGNORECASE,
)


def _convert_maxrecursion(sql: str) -> tuple[str, list[str]]:
    """Replace OPTION (MAXRECURSION n) with a PostgreSQL SET LOCAL comment."""
    warnings: list[str] = []

    def _replace(m: re.Match) -> str:  # type: ignore[type-arg]
        depth = m.group(1)
        warnings.append(
            f"MAXRECURSION {depth}: replaced with SET LOCAL comment — "
            "add 'SET LOCAL max_recursion_depth = {depth};' before this CTE"
        )
        return (
            f"/* ⚠️ MAXRECURSION {depth} converted: "
            f"SET LOCAL max_recursion_depth = {depth}; "
            f"(run before this query in a transaction) */"
        )

    sql = _MAXRECURSION_PATTERN.sub(_replace, sql)
    return sql, warnings


# ---------------------------------------------------------------------------
# Global temporary table (##) flagging
# ---------------------------------------------------------------------------

# Match ##identifier  — double-hash is SQL Server global temp table syntax
_GLOBAL_TEMP_PATTERN = re.compile(r"##([a-zA-Z_]\w*)", re.IGNORECASE)


def _flag_global_temp_tables(sql: str) -> tuple[str, list[str]]:
    """Replace ##name references with a warning annotation and tmp_name."""
    warnings: list[str] = []
    found: set[str] = set()

    def _replace(m: re.Match) -> str:  # type: ignore[type-arg]
        name = m.group(1)
        found.add(name)
        return (
            f"tmp_{name} "
            f"/* ⚠️ MANUAL REVIEW REQUIRED: global temp table renamed to tmp_{name} — "
            f"PostgreSQL has no global temp tables; use an UNLOGGED table or "
            f"a schema-qualified regular table and drop it after the session */"
        )

    sql = _GLOBAL_TEMP_PATTERN.sub(_replace, sql)
    if found:
        warnings.append(
            f"Global temp tables: {', '.join('##' + n for n in sorted(found))} — "
            "⚠️ MANUAL REVIEW REQUIRED: renamed to tmp_<name>"
        )
    return sql, warnings


# ---------------------------------------------------------------------------
# MERGE statement conversion
# ---------------------------------------------------------------------------

# Detect the start of a MERGE statement.
# Full MERGE parsing is too complex for regex; we handle two cases:
#  1. Simple MERGE with WHEN MATCHED UPDATE + WHEN NOT MATCHED INSERT
#     → convert to INSERT … ON CONFLICT DO UPDATE
#  2. All other MERGE patterns → annotate with MANUAL REVIEW
_MERGE_START = re.compile(r"\bMERGE\b", re.IGNORECASE)

# Captures simple MERGE upsert pattern:
#   MERGE <target> [AS t]
#   USING <source> [AS s] ON <condition>
#   WHEN MATCHED THEN UPDATE SET <assignments>
#   WHEN NOT MATCHED THEN INSERT (<cols>) VALUES (<vals>);
_SIMPLE_MERGE_RE = re.compile(
    r"""
    MERGE\s+(?:INTO\s+)?                        # MERGE [INTO]
    (?P<target>\[?\w+\]?(?:\.\[?\w+\]?)?)       # target table
    \s+(?:AS\s+\w+\s+)?                         # optional alias
    USING\s+                                    # USING
    (?P<source>\[?\w+\]?(?:\.\[?\w+\]?)?)       # source table
    \s+(?:AS\s+\w+\s+)?ON\s+                    # optional alias + ON
    (?P<condition>[^\n]+?)\s+                   # join condition
    WHEN\s+MATCHED\s+THEN\s+UPDATE\s+SET\s+     # WHEN MATCHED UPDATE
    (?P<updates>[^W]+?)                         # SET assignments
    WHEN\s+NOT\s+MATCHED\s+(?:BY\s+TARGET\s+)?THEN\s+INSERT\s* # WHEN NOT MATCHED INSERT
    \((?P<ins_cols>[^)]+)\)\s*VALUES\s*
    \((?P<ins_vals>[^)]+)\)\s*;
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)

_MERGE_FALLBACK_COMMENT = """\
/* ⚠️ MANUAL REVIEW REQUIRED: MERGE statement detected.
   SQL Server MERGE semantics differ from PostgreSQL.
   Rewrite as: INSERT INTO ... (...) SELECT ... FROM ...
               ON CONFLICT (<key_cols>) DO UPDATE SET ...;
   See: https://www.postgresql.org/docs/current/sql-insert.html */
"""


def _convert_merge(sql: str) -> tuple[str, list[str]]:
    """Convert simple MERGE upserts; annotate complex ones for manual review."""
    if not _MERGE_START.search(sql):
        return sql, []

    warnings: list[str] = []
    m = _SIMPLE_MERGE_RE.search(sql)

    if m:
        target = m.group("target").strip().strip("[]")
        source = m.group("source").strip().strip("[]")
        condition = m.group("condition").strip()
        updates_raw = m.group("updates").strip().rstrip(",")
        ins_cols = m.group("ins_cols").strip()
        ins_vals = m.group("ins_vals").strip()

        # Build conflict columns from ON condition (e.g. "t.id = s.id" → "id")
        conflict_cols = _extract_conflict_cols(condition)
        conflict_clause = f"({conflict_cols})" if conflict_cols else "(id)"

        # Build DO UPDATE SET — strip table alias prefixes
        update_set = _strip_alias_prefix(updates_raw)

        converted = (
            f"-- ⚠️ MERGE converted to INSERT … ON CONFLICT (verify semantics)\n"
            f"INSERT INTO {target} ({ins_cols})\n"
            f"SELECT {ins_vals} FROM {source}\n"
            f"ON CONFLICT {conflict_clause} DO UPDATE SET\n"
            f"    {update_set};"
        )
        sql = sql[: m.start()] + converted + sql[m.end():]
        warnings.append(
            "MERGE: simple upsert pattern converted to INSERT ON CONFLICT — "
            "verify ON CONFLICT column list and EXCLUDED references manually"
        )
    else:
        # Complex MERGE: annotate at the start of the statement
        sql = _MERGE_START.sub(
            _MERGE_FALLBACK_COMMENT + "MERGE",
            sql,
            count=1,
        )
        warnings.append(
            "MERGE: complex MERGE detected — ⚠️ MANUAL REVIEW REQUIRED; "
            "automatic conversion not possible for this pattern"
        )

    return sql, warnings


def _extract_conflict_cols(condition: str) -> str:
    """Extract the right-hand column from a simple 'alias.col = alias.col' join condition."""
    # e.g.  "t.id = s.id"  →  "id"
    parts = re.split(r"\s*=\s*", condition.strip())
    if len(parts) == 2:
        col = parts[0].strip()
        # Remove table alias prefix
        if "." in col:
            col = col.split(".")[-1]
        return col.strip("[]")
    return ""


def _strip_alias_prefix(assignments: str) -> str:
    """Remove table alias prefixes from SET assignments.

    e.g. ``t.name = s.name, t.val = s.val``
      →  ``name = EXCLUDED.name, val = EXCLUDED.val``
    """
    # Replace "alias.col = src_alias.col" → "col = EXCLUDED.col"
    result = re.sub(
        r"(?:\w+\.)(\w+)\s*=\s*(?:\w+\.)(\w+)",
        r"\1 = EXCLUDED.\2",
        assignments,
        flags=re.IGNORECASE,
    )
    return result


# ---------------------------------------------------------------------------
# RAISERROR → RAISE EXCEPTION  /  THROW → RAISE EXCEPTION
# ---------------------------------------------------------------------------

# Optional WITH options trailing RAISERROR: WITH LOG, WITH SETERROR, WITH NOWAIT
_WITH_OPTS = r"(?:\s+WITH\s+(?:LOG|SETERROR|NOWAIT)(?:\s*,\s*(?:LOG|SETERROR|NOWAIT))*)?"

# Literal-string message: RAISERROR([N]'msg', severity, state) [WITH ...]
_RAISERROR_LITERAL = re.compile(
    r"\bRAISERROR\s*\(\s*N?'([^']*)'\s*,\s*\d+\s*,\s*\d+\s*\)" + _WITH_OPTS + r"\s*;?",
    re.IGNORECASE,
)

# Variable message: RAISERROR(@var, severity, state) [WITH ...]
_RAISERROR_VARIABLE = re.compile(
    r"\bRAISERROR\s*\(\s*(@\w+)\s*,\s*\d+\s*,\s*\d+\s*\)" + _WITH_OPTS + r"\s*;?",
    re.IGNORECASE,
)

# Catch-all — any remaining RAISERROR after the above two have run
_RAISERROR_ANY = re.compile(r"\bRAISERROR\b", re.IGNORECASE)

# THROW error_number, [N]'message', state;  (SQL Server 2012+)
# Bare THROW; (re-throw inside CATCH) is also handled.
_THROW_WITH_ARGS = re.compile(
    r"\bTHROW\s+\d+\s*,\s*N?'([^']*)'\s*,\s*\d+\s*;?",
    re.IGNORECASE,
)
_THROW_BARE = re.compile(r"\bTHROW\s*;", re.IGNORECASE)

_RAISERROR_MANUAL = (
    "/* ⚠️ MANUAL REVIEW REQUIRED: RAISERROR with format/substitution arguments — "
    "rewrite as: RAISE EXCEPTION '... %s ...', arg1, arg2, ...; */"
)


def _convert_raiserror(sql: str) -> tuple[str, list[str]]:
    """Convert RAISERROR / THROW to PL/pgSQL RAISE EXCEPTION.

    Handles:
    * Literal msg:  RAISERROR('msg', 16, 1)        → RAISE EXCEPTION 'msg';
    * N-prefix:     RAISERROR(N'msg', 16, 1)        → RAISE EXCEPTION 'msg';
    * WITH opts:    RAISERROR('msg', 16, 1) WITH NOWAIT → RAISE EXCEPTION 'msg';
    * Variable:     RAISERROR(@var, 16, 1)           → RAISE EXCEPTION '%', var;
    * THROW args:   THROW 51000, 'msg', 1            → RAISE EXCEPTION 'msg';
    * Bare THROW;                                    → RAISE;
    * Complex:      RAISERROR('fmt %d', 16, 1, @n)  → annotated MANUAL REVIEW
    """
    has_raiserror = _RAISERROR_ANY.search(sql)
    has_throw = re.search(r"\bTHROW\b", sql, re.IGNORECASE)
    if not has_raiserror and not has_throw:
        return sql, []

    warnings: list[str] = []

    # --- THROW bare re-throw ---
    if _THROW_BARE.search(sql):
        sql = _THROW_BARE.sub("RAISE;", sql)
        warnings.append("THROW: bare THROW; (re-throw) converted to RAISE;")

    # --- THROW with arguments ---
    def _replace_throw(m: re.Match) -> str:  # type: ignore[type-arg]
        msg = m.group(1)
        warnings.append(f"THROW: converted to RAISE EXCEPTION '{msg}'")
        return f"RAISE EXCEPTION '{msg}';"

    sql = _THROW_WITH_ARGS.sub(_replace_throw, sql)

    # --- RAISERROR literal ---
    def _replace_literal(m: re.Match) -> str:  # type: ignore[type-arg]
        msg = m.group(1)
        warnings.append(f"RAISERROR: converted literal message to RAISE EXCEPTION '{msg}'")
        return f"RAISE EXCEPTION '{msg}';"

    sql = _RAISERROR_LITERAL.sub(_replace_literal, sql)

    # --- RAISERROR variable ---
    def _replace_variable(m: re.Match) -> str:  # type: ignore[type-arg]
        var = m.group(1).lstrip("@")  # drop @ prefix for PL/pgSQL variable syntax
        warnings.append(f"RAISERROR: converted @{var} reference to RAISE EXCEPTION '%', {var}")
        return f"RAISE EXCEPTION '%', {var};"

    sql = _RAISERROR_VARIABLE.sub(_replace_variable, sql)

    # --- Any remaining RAISERROR (format-string / complex form) → annotate ---
    if _RAISERROR_ANY.search(sql):
        def _annotate_complex(m: re.Match) -> str:  # type: ignore[type-arg]
            return _RAISERROR_MANUAL + "\n" + m.group(0)

        sql = _RAISERROR_ANY.sub(_annotate_complex, sql, count=1)
        warnings.append(
            "RAISERROR: format-string RAISERROR detected — "
            "⚠️ MANUAL REVIEW REQUIRED; rewrite as RAISE EXCEPTION '... %s ...', args"
        )

    return sql, warnings


# ---------------------------------------------------------------------------
# OUTPUT clause → RETURNING
# ---------------------------------------------------------------------------

# Column identifier after INSERTED./DELETED.: bare word or bracket-quoted [name].
# Using [\w\[\]]+ prevents consuming trailing commas (unlike \S+).
_OUTPUT_COL = r"(?:INSERTED|DELETED)\.[\w\[\]]+"
_OUTPUT_COL_LIST = (
    r"(?:" + _OUTPUT_COL + r")"                        # first column
    r"(?:\s*,\s*(?:" + _OUTPUT_COL + r"))*"            # additional columns
)
_OUTPUT_CLAUSE = re.compile(
    r"\bOUTPUT\s+(" + _OUTPUT_COL_LIST + r")",
    re.IGNORECASE,
)


def _strip_inserted_deleted(col_list: str) -> str:
    """Remove INSERTED. / DELETED. prefixes, returning a plain column list."""
    return re.sub(r"\b(?:INSERTED|DELETED)\.", "", col_list, flags=re.IGNORECASE)


def _convert_output_clause(sql: str) -> tuple[str, list[str]]:
    """Convert OUTPUT INSERTED./DELETED. to PostgreSQL RETURNING.

    * INSERT/UPDATE/DELETE … OUTPUT INSERTED.col, DELETED.col …
      → same DML without OUTPUT, with RETURNING col, col appended.
    * OUTPUT INTO @table_var  → annotated for MANUAL REVIEW (no PG equivalent).
    """
    if not re.search(r"\bOUTPUT\b", sql, re.IGNORECASE):
        return sql, []

    warnings: list[str] = []

    # --- OUTPUT INTO <table variable>: no PG equivalent, annotate only ---
    if re.search(r"\bOUTPUT\b.+\bINTO\b", sql, re.IGNORECASE | re.DOTALL):
        sql = re.sub(
            r"\bOUTPUT\b[^;]+?\bINTO\s+@?\w+",
            "/* MANUAL REVIEW: OUTPUT INTO table variable — rewrite using CTE with RETURNING */",
            sql,
            flags=re.IGNORECASE,
        )
        warnings.append(
            "OUTPUT INTO: MANUAL REVIEW REQUIRED — "
            "rewrite using a CTE with RETURNING"
        )
        return sql, warnings

    def _convert_one_statement(stmt: str) -> str:
        m = _OUTPUT_CLAUSE.search(stmt)
        if not m:
            return stmt

        returning_cols = _strip_inserted_deleted(m.group(1)).strip()
        without_output = stmt[: m.start()] + stmt[m.end() :]
        core = without_output.rstrip().rstrip(";").rstrip()
        converted = f"{core} RETURNING {returning_cols};"
        warnings.append(
            f"OUTPUT: converted to RETURNING {returning_cols} — "
            "verify column names match the target table definition"
        )
        return converted

    # Convert OUTPUT per semicolon-delimited statement so RETURNING stays on the DML.
    if ";" in sql:
        parts = re.split(r"(;)", sql)
        statements: list[str] = []
        buf = ""
        for part in parts:
            buf += part
            if part == ";":
                statements.append(buf)
                buf = ""
        if buf:
            statements.append(buf)
        return "".join(_convert_one_statement(s) for s in statements), warnings

    return _convert_one_statement(sql), warnings
