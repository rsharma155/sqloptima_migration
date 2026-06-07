"""
T-SQL parse unblockers — normalize source SQL so SQLGlot / ANTLR can parse it.

Applied upstream before transpilation (Phase C). Each step returns (sql, changes).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

_BRACKET_IDENT_RE = re.compile(r"\[([^\]]+)\]")

_GO_LINE_RE = re.compile(r"^\s*GO\s*$", re.IGNORECASE | re.MULTILINE)

_SESSION_SET_RE = re.compile(
    r"^\s*SET\s+(?:"
    r"NOCOUNT|XACT_ABORT|QUOTED_IDENTIFIER|ANSI_NULLS|ANSI_PADDING|"
    r"ARITHABORT|NUMERIC_ROUNDABORT|CONCAT_NULL_YIELDS_NULL|"
    r"IDENTITY_INSERT|ROWCOUNT|TEXTSIZE|LANGUAGE|DATEFIRST|DATEFORMAT|DEADLOCK_PRIORITY"
    r")\s+[^;]*;?\s*$",
    re.IGNORECASE | re.MULTILINE,
)

_PROC_OPTION_RE = re.compile(
    r"\bWITH\s+(?:ENCRYPTION|RECOMPILE|SCHEMABINDING|NATIVE_COMPILATION|"
    r"EXECUTE\s+AS\s+(?:CALLER|OWNER|SELF)|CERTIFICATE\s+\w+|"
    r"EXECUTE\s+AS\s+LOGIN\s*=\s*[^,\s]+)\b",
    re.IGNORECASE,
)

_TABLE_HINT_RE = re.compile(
    r"\bWITH\s*\(\s*"
    r"(?:NOLOCK|ROWLOCK|XLOCK|UPDLOCK|HOLDLOCK|READPAST|TABLOCKX?|TABLOCK|"
    r"NOWAIT|PAGLOCK|READUNCOMMITTED|REPEATABLEREAD|SERIALIZABLE|"
    r"INDEX\s*\([^)]+\))\s*"
    r"(?:,\s*\w+\s*(?:\([^)]*\))?)*\)",
    re.IGNORECASE,
)

_N_STRING_RE = re.compile(r"\bN'", re.IGNORECASE)

# T-SQL label before statement (e.g. retry: SELECT ...)
_LABEL_PREFIX_RE = re.compile(r"^\s*(\w+)\s*:\s*", re.MULTILINE)


@dataclass
class UnblockResult:
    """Outcome of applying parse unblockers to T-SQL source."""

    sql: str
    steps_applied: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def normalize_line_endings(sql: str) -> tuple[str, int]:
    if "\r" not in sql:
        return sql, 0
    return sql.replace("\r\n", "\n").replace("\r", "\n"), 1


def strip_go_batch_separators(sql: str) -> tuple[str, int]:
    matches = list(_GO_LINE_RE.finditer(sql))
    if not matches:
        return sql, 0
    return _GO_LINE_RE.sub("\n", sql), len(matches)


def normalize_bracket_identifiers(sql: str) -> tuple[str, int]:
    count = 0

    def _repl(m: re.Match[str]) -> str:
        nonlocal count
        count += 1
        name = m.group(1)
        if re.match(r"^\w+$", name):
            return name
        return f'"{name}"'

    return _BRACKET_IDENT_RE.sub(_repl, sql), count


def strip_session_settings(sql: str) -> tuple[str, int]:
    matches = list(_SESSION_SET_RE.finditer(sql))
    if not matches:
        return sql, 0
    return _SESSION_SET_RE.sub("", sql), len(matches)


def strip_procedure_options(sql: str) -> tuple[str, int]:
    matches = list(_PROC_OPTION_RE.finditer(sql))
    if not matches:
        return sql, 0
    return _PROC_OPTION_RE.sub("", sql), len(matches)


def strip_table_hints(sql: str) -> tuple[str, int]:
    matches = list(_TABLE_HINT_RE.finditer(sql))
    if not matches:
        return sql, 0
    return _TABLE_HINT_RE.sub("", sql), len(matches)


def normalize_unicode_string_prefix(sql: str) -> tuple[str, int]:
    matches = list(_N_STRING_RE.finditer(sql))
    if not matches:
        return sql, 0
    return _N_STRING_RE.sub("'", sql), len(matches)


def comment_goto_labels(sql: str) -> tuple[str, int]:
    """Turn T-SQL labels (target:) into comments so parsers don't choke."""
    matches = list(_LABEL_PREFIX_RE.finditer(sql))
    if not matches:
        return sql, 0

    def _repl(m: re.Match[str]) -> str:
        return f"/* label:{m.group(1)} */ "

    return _LABEL_PREFIX_RE.sub(_repl, sql), len(matches)


def comment_goto_statements(sql: str) -> tuple[str, int]:
    pattern = re.compile(r"^\s*GOTO\s+\w+\s*;?\s*$", re.IGNORECASE | re.MULTILINE)
    matches = list(pattern.finditer(sql))
    if not matches:
        return sql, 0
    return pattern.sub("/* GOTO removed for parse */", sql), len(matches)


def collapse_blank_lines(sql: str) -> tuple[str, int]:
    collapsed = re.sub(r"\n{3,}", "\n\n", sql)
    if collapsed == sql:
        return sql, 0
    return collapsed, 1


# Light pass — safe for headers and bodies.
LIGHT_STEPS: list[tuple[str, Callable[[str], tuple[str, int]]]] = [
    ("normalize_line_endings", normalize_line_endings),
    ("strip_go", strip_go_batch_separators),
    ("normalize_brackets", normalize_bracket_identifiers),
    ("normalize_unicode_strings", normalize_unicode_string_prefix),
    ("strip_session_settings", strip_session_settings),
    ("collapse_blank_lines", collapse_blank_lines),
]

# Aggressive pass — may alter semantics slightly; used on retry.
AGGRESSIVE_STEPS: list[tuple[str, Callable[[str], tuple[str, int]]]] = [
    ("strip_procedure_options", strip_procedure_options),
    ("strip_table_hints", strip_table_hints),
    ("comment_goto_labels", comment_goto_labels),
    ("comment_goto_statements", comment_goto_statements),
]


class TsqlParseUnblocker:
    """Apply ordered parse-unblocker steps to T-SQL source."""

    @staticmethod
    def apply(sql: str, *, aggressive: bool = False) -> UnblockResult:
        steps = LIGHT_STEPS + (AGGRESSIVE_STEPS if aggressive else [])
        current = sql
        applied: list[str] = []
        warnings: list[str] = []

        for name, fn in steps:
            updated, count = fn(current)
            if count:
                applied.append(name)
                current = updated
                if name in ("strip_procedure_options", "comment_goto_statements"):
                    warnings.append(
                        f"Parse unblocker '{name}' applied — review converted control flow"
                    )

        if applied:
            warnings.insert(
                0,
                f"Applied {len(applied)} T-SQL parse unblocker(s): {', '.join(applied)}",
            )

        return UnblockResult(sql=current, steps_applied=applied, warnings=warnings)

    @staticmethod
    def apply_with_retry(sql: str) -> UnblockResult:
        """Light pass first; aggressive pass only when light pass changed nothing meaningful."""
        light = TsqlParseUnblocker.apply(sql, aggressive=False)
        if light.steps_applied:
            return light
        return TsqlParseUnblocker.apply(sql, aggressive=True)
