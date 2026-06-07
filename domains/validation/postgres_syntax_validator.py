"""
Module: postgres_syntax_validator.py
Purpose: Validate converted PostgreSQL / PL/pgSQL output using libpg_query (pgparse)
         plus pattern checks for common unconverted T-SQL remnants.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

try:
    import pgparse

    _PGPARSE_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised when pgparse is not installed
    pgparse = None  # type: ignore[assignment,misc]
    _PGPARSE_AVAILABLE = False

# T-SQL remnants that PostgreSQL rejects or that indicate incomplete conversion.
_TSQL_REMNANT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bWITH\s*\(\s*NOLOCK\s*\)", re.IGNORECASE), "SQL Server table hint WITH (NOLOCK)"),
    (re.compile(r"\bEXEC\s+sp_executesql\b", re.IGNORECASE), "SQL Server dynamic SQL EXEC sp_executesql"),
    (re.compile(r"\bsp_executesql\b", re.IGNORECASE), "SQL Server sp_executesql"),
    (re.compile(r"\bGOTO\b", re.IGNORECASE), "SQL Server GOTO (not supported in PL/pgSQL)"),
    (re.compile(r"\bIDENTITY\s*\(", re.IGNORECASE), "SQL Server IDENTITY() column property"),
    (re.compile(r"\bBEGIN\s+TRY\b", re.IGNORECASE), "SQL Server BEGIN TRY block"),
    (re.compile(r"\bBEGIN\s+CATCH\b", re.IGNORECASE), "SQL Server BEGIN CATCH block"),
    (re.compile(r"\bRAISERROR\s*\(", re.IGNORECASE), "SQL Server RAISERROR()"),
    (re.compile(r"@@ROWCOUNT\b", re.IGNORECASE), "SQL Server @@ROWCOUNT"),
    (re.compile(r"@@IDENTITY\b", re.IGNORECASE), "SQL Server @@IDENTITY"),
    (re.compile(r"\bSYSTEM_USER\b", re.IGNORECASE), "SQL Server SYSTEM_USER"),
    (re.compile(r"\bTOP\s+\d+\b", re.IGNORECASE), "SQL Server TOP N (use LIMIT)"),
    (re.compile(r"\bNVARCHAR\s*\(\s*MAX\s*\)", re.IGNORECASE), "SQL Server NVARCHAR(MAX)"),
    (re.compile(r"\bVARCHAR\s*\(\s*MAX\s*\)", re.IGNORECASE), "SQL Server VARCHAR(MAX)"),
)

_DOLLAR_BODY_RE = re.compile(
    r"\bAS\s+\$([\w]*)\$(.*?)\$\1\s*;",
    re.IGNORECASE | re.DOTALL,
)

_SQL_FRAGMENT_START = re.compile(
    r"^\s*(SELECT|INSERT|UPDATE|DELETE|WITH|MERGE|CREATE|TRUNCATE|ALTER|DROP)\b",
    re.IGNORECASE,
)


@dataclass
class SyntaxIssue:
    """A single PostgreSQL syntax or validation issue."""

    message: str
    position: int | None = None
    line: int | None = None


@dataclass
class PostgresSyntaxResult:
    """Outcome of validating converted PostgreSQL output."""

    valid: bool
    errors: list[SyntaxIssue] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    parser: str = "pgparse"


def _line_for_position(sql: str, position: int | None) -> int | None:
    if position is None or position < 0:
        return None
    return sql[:position].count("\n") + 1


def _extract_dollar_bodies(sql: str) -> list[str]:
    return [match.group(2) for match in _DOLLAR_BODY_RE.finditer(sql)]


def _split_fragments(body: str) -> list[str]:
    """Split a PL/pgSQL body on semicolons outside single-quoted strings."""
    fragments: list[str] = []
    current: list[str] = []
    in_string = False
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "'" and not in_string:
            in_string = True
            current.append(ch)
        elif ch == "'" and in_string:
            if i + 1 < len(body) and body[i + 1] == "'":
                current.append("''")
                i += 1
            else:
                in_string = False
                current.append(ch)
        elif ch == ";" and not in_string:
            fragment = "".join(current).strip()
            if fragment:
                fragments.append(fragment)
            current = []
        else:
            current.append(ch)
        i += 1
    tail = "".join(current).strip()
    if tail:
        fragments.append(tail)
    return fragments


class PostgresSyntaxValidator:
    """Validate converted PostgreSQL / PL/pgSQL using libpg_query and pattern checks."""

    def validate(self, sql: str) -> PostgresSyntaxResult:
        if not sql or not sql.strip():
            return PostgresSyntaxResult(
                valid=False,
                errors=[SyntaxIssue(message="Converted SQL is empty")],
                parser="none",
            )

        errors: list[SyntaxIssue] = []
        warnings: list[str] = []

        errors.extend(self._pattern_issues(sql))

        if not _PGPARSE_AVAILABLE:
            warnings.append(
                "PostgreSQL parser (pgparse) is not installed; only pattern-based checks were run."
            )
            return PostgresSyntaxResult(
                valid=not errors,
                errors=errors,
                warnings=warnings,
                parser="pattern",
            )

        errors.extend(self._parse_sql(sql))

        bodies = _extract_dollar_bodies(sql)
        if bodies:
            for body in bodies:
                errors.extend(self._pattern_issues(body))
                errors.extend(self._validate_plpgsql_body(body, sql))
        elif not errors:
            # Raw SQL without dollar-quoted routines: full-statement parse is enough.
            pass

        # Deduplicate by message while preserving order.
        seen: set[str] = set()
        unique_errors: list[SyntaxIssue] = []
        for issue in errors:
            key = issue.message
            if key not in seen:
                seen.add(key)
                unique_errors.append(issue)

        return PostgresSyntaxResult(
            valid=not unique_errors,
            errors=unique_errors,
            warnings=warnings,
            parser="pgparse",
        )

    def _pattern_issues(self, text: str) -> list[SyntaxIssue]:
        issues: list[SyntaxIssue] = []
        for pattern, label in _TSQL_REMNANT_PATTERNS:
            for match in pattern.finditer(text):
                issues.append(
                    SyntaxIssue(
                        message=f"Unconverted T-SQL remnant: {label}",
                        position=match.start(),
                        line=_line_for_position(text, match.start()),
                    )
                )
        return issues

    def _parse_sql(self, sql: str) -> list[SyntaxIssue]:
        assert pgparse is not None
        try:
            pgparse.parse(sql)
        except pgparse.PGQueryError as exc:
            return [
                SyntaxIssue(
                    message=f"PostgreSQL syntax error: {exc.message}",
                    position=exc.position,
                    line=_line_for_position(sql, exc.position),
                )
            ]
        return []

    def _prepare_embedded_fragment(self, fragment: str) -> str | None:
        """Return SQL suitable for pgparse, or None to skip valid PL/pgSQL-only constructs."""
        stripped = fragment.strip()
        if not stripped:
            return None

        upper = stripped.upper()
        if upper.startswith(("IF ", "WHILE ", "FOR ", "LOOP ", "CASE ", "RETURN;", "RETURN\n")):
            return None
        if re.match(r"^RETURN\s*;\s*$", stripped, re.IGNORECASE):
            return None
        if re.match(r"^(RAISE|PERFORM|EXECUTE|GET DIAGNOSTICS|EXEC)\b", stripped, re.IGNORECASE):
            return None
        # PL/pgSQL dynamic DML — valid inside procedures, not standalone SQL.
        if re.search(
            r"^\s*(INSERT|UPDATE|DELETE)\b[\s\S]*\bEXECUTE\b",
            stripped,
            re.IGNORECASE,
        ):
            return None
        if re.match(r"^EXCEPTION\b", stripped, re.IGNORECASE):
            return None
        if re.match(r"^RETURN\b(?!\s+QUERY\b)", stripped, re.IGNORECASE):
            return None
        if re.match(r"^CREATE\s+(?:TEMP|TEMPORARY)\s+TABLE\b", stripped, re.IGNORECASE):
            return None
        if re.match(r"^DROP\s+(?:TABLE|INDEX|VIEW)\b", stripped, re.IGNORECASE):
            return None
        # Multi-statement PL/pgSQL fragments (conversion may omit inner semicolons).
        if re.search(r"\bSELECT\b", stripped, re.IGNORECASE) and re.search(
            r"\bDROP\s+TABLE\b", stripped, re.IGNORECASE
        ):
            return None

        # RETURN QUERY is PL/pgSQL-specific; inner SELECT may still contain T-SQL.
        if re.search(r"\bRETURN\s+QUERY\b", stripped, re.IGNORECASE):
            return None

        # PL/pgSQL SELECT ... INTO variable — valid in procedures, not pure SQL.
        if re.search(r"\bINTO\s+(?:p_|v_)\w+\b", stripped, re.IGNORECASE):
            return None

        if not _SQL_FRAGMENT_START.match(stripped):
            return None

        return stripped if stripped.endswith(";") else f"{stripped};"

    def _validate_plpgsql_body(self, body: str, full_sql: str) -> list[SyntaxIssue]:
        assert pgparse is not None
        issues: list[SyntaxIssue] = []

        for fragment in _split_fragments(body):
            stmt = self._prepare_embedded_fragment(fragment)
            if stmt is None:
                continue
            try:
                pgparse.parse(stmt)
            except pgparse.PGQueryError as exc:
                offset = full_sql.find(fragment)
                pos = (offset + exc.position) if offset >= 0 and exc.position is not None else exc.position
                issues.append(
                    SyntaxIssue(
                        message=f"Embedded SQL syntax error: {exc.message}",
                        position=pos,
                        line=_line_for_position(full_sql, pos),
                    )
                )
        return issues
