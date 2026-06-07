"""
Module: domains/transpilation/converters/plpgsql/_header_parser.py
Purpose: Parses the T-SQL CREATE PROCEDURE / CREATE FUNCTION header to extract
         the schema name, object name, parameter list, and procedure body.

         Two public surface-area items:
           - ``_extract_body(sql)`` — extracts the body between AS BEGIN … END
           - ``TsqlHeaderParser.parse(sql)`` — full header + body extraction

Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import re
from typing import Optional

from domains.transpilation.converters.plpgsql._models import HeaderInfo, ParamInfo
from domains.transpilation.converters.plpgsql._type_mapper import TsqlTypeMapper


# ---------------------------------------------------------------------------
# Body extraction
# ---------------------------------------------------------------------------


def _extract_body(sql: str) -> str:
    """Return the procedure body between ``AS BEGIN … END`` (outermost pair).

    Strips the outer ``BEGIN`` / ``END`` wrapper and any trailing ``GO``
    batch separator, leaving the raw T-SQL statements that form the body.
    """
    # Find the AS keyword that introduces the body
    as_match = re.search(r'\bAS\b\s*\n', sql, re.IGNORECASE)
    if not as_match:
        as_match = re.search(r'\bAS\b\s+BEGIN\b', sql, re.IGNORECASE)
    if not as_match:
        # No AS found — grab everything after the first BEGIN
        begin_m = re.search(r'\bBEGIN\b', sql, re.IGNORECASE)
        if begin_m:
            body_raw = sql[begin_m.end():]
        else:
            return sql.strip()
    else:
        body_raw = sql[as_match.end():]

    # Strip outer BEGIN … END wrapper
    body_stripped = body_raw.strip()
    if body_stripped.upper().startswith("BEGIN"):
        body_stripped = body_stripped[5:].strip()

    # Remove trailing END [;] [GO]
    body_stripped = re.sub(
        r'\bEND\s*;?\s*(?:GO)?\s*$', '', body_stripped,
        flags=re.IGNORECASE,
    ).strip()

    # Remove any trailing lone GO
    body_stripped = re.sub(r'\bGO\s*$', '', body_stripped, flags=re.IGNORECASE).strip()

    return body_stripped


# ---------------------------------------------------------------------------
# Parameter block splitter
# ---------------------------------------------------------------------------


def _split_params(
    param_text: str,
) -> list[tuple[str, str, bool, bool, Optional[str]]]:
    """Split raw parameter text into ``(name, raw_type, is_output, is_readonly, default)`` tuples.

    Correctly handles:
    - Commas inside length specifiers like ``DECIMAL(18, 4)``
    - Output / READONLY modifiers
    - Optional default values (quoted strings, numbers, NULL)
    """
    results: list[tuple[str, str, bool, bool, Optional[str]]] = []
    text = re.sub(r'\s+', ' ', param_text).strip().rstrip(',')

    # Split on commas that are NOT inside parentheses
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in text:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        if ch == ',' and depth == 0:
            parts.append(''.join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        parts.append(''.join(current).strip())

    for part in parts:
        part = part.strip()
        if not part:
            continue

        is_output = bool(re.search(r'\b(?:OUTPUT|OUT)\b', part, re.IGNORECASE))
        is_readonly = bool(re.search(r'\bREADONLY\b', part, re.IGNORECASE))

        # Strip trailing modifiers before parsing type / default
        cleaned = re.sub(r'\s+(?:OUTPUT|OUT|READONLY)\s*$', '', part.strip(), flags=re.IGNORECASE)
        cleaned = re.sub(r'\s+(?:OUTPUT|OUT|READONLY)\b', ' ', cleaned, flags=re.IGNORECASE).strip()

        m = re.match(
            r'@(\w+)'                              # @name
            r'\s+'
            r'([\w][\w\s\.\(\),]*?)'               # type (schema-qualified OK)
            r'(?:\s*=\s*'                          # optional default
            r"(N?'[^']*'"                          # quoted string
            r'|-?\d+(?:\.\d+)?'                    # number
            r'|NULL|TRUE|FALSE'
            r'))?'
            r'\s*$',
            cleaned, re.IGNORECASE,
        )
        if not m:
            m2 = re.match(r'@(\w+)\s+([\w][\w.\s\(\)]*)', part, re.IGNORECASE)
            if m2:
                results.append((m2.group(1), m2.group(2).strip(), is_output, is_readonly, None))
            continue

        results.append((m.group(1), m.group(2).strip(), is_output, is_readonly, m.group(3)))

    return results


# ---------------------------------------------------------------------------
# TsqlHeaderParser
# ---------------------------------------------------------------------------


class TsqlHeaderParser:
    """Parses a T-SQL ``CREATE PROCEDURE`` / ``CREATE FUNCTION`` header.

    Extracts:
    - Object schema and name
    - Full parameter list with types, defaults, and OUTPUT/READONLY modifiers
    - The procedure body (text between ``AS BEGIN`` … ``END``)
    """

    @staticmethod
    def parse(sql: str) -> HeaderInfo:
        """Parse *sql* and return a populated :class:`HeaderInfo`."""
        info = HeaderInfo()

        # ── 1. Object type ────────────────────────────────────────────────
        info.is_function = bool(
            re.search(r'\bCREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\b', sql, re.IGNORECASE)
        )

        # ── 2. Schema and name ────────────────────────────────────────────
        name_m = re.search(
            r'\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:PROCEDURE|PROC|FUNCTION)\s+'
            r'(?:\[?(\w+)\]?\.)?\[?(\w+)\]?',
            sql, re.IGNORECASE,
        )
        if name_m:
            info.schema = name_m.group(1) or "dbo"
            info.name   = name_m.group(2)

        # ── 3. Parameter block ────────────────────────────────────────────
        after_name_m = re.search(
            r'\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:PROCEDURE|PROC|FUNCTION)\s+'
            r'(?:\[?\w+\]?\.)?\[?\w+\]?\s*',
            sql, re.IGNORECASE,
        )
        rest = sql[after_name_m.end():] if after_name_m else sql

        # Strip WITH ENCRYPTION / RECOMPILE / EXECUTE AS options before AS
        rest = re.sub(
            r'\bWITH\s+(?:ENCRYPTION|RECOMPILE|EXECUTE\s+AS\s+\w+)'
            r'(?:\s*,\s*(?:ENCRYPTION|RECOMPILE))*',
            '', rest, flags=re.IGNORECASE,
        )

        as_m = re.search(r'\bAS\b\s*\n?', rest, re.IGNORECASE)
        param_block = rest[: as_m.start()].strip() if as_m else ""
        param_block = param_block.strip()
        if param_block.startswith('(') and param_block.endswith(')'):
            param_block = param_block[1:-1]

        if param_block:
            for name, raw_type, is_out, is_ro, default_raw in _split_params(param_block):
                pg_type    = TsqlTypeMapper.map(raw_type)
                pg_default = TsqlTypeMapper.map_default(default_raw, raw_type)
                if pg_default and pg_default.startswith("N'"):
                    pg_default = pg_default[1:]  # strip N prefix from unicode literals
                info.parameters.append(ParamInfo(
                    name=name,
                    pg_type=pg_type,
                    is_output=is_out,
                    is_readonly=is_ro,
                    default_value=pg_default,
                ))

        # ── 4. Body ───────────────────────────────────────────────────────
        info.body = _extract_body(sql)

        return info
