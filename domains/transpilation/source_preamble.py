"""Preserve leading comments and metadata from T-SQL source scripts.

Extracts file-header comments (``--`` and ``/* */``) that appear before the
first SQL statement so they can be re-attached to converted output.
"""
from __future__ import annotations

import re

_SQL_START = re.compile(
    r"^\s*(?:CREATE|ALTER|DROP|EXEC(?:UTE)?|DECLARE|INSERT|UPDATE|DELETE|SELECT|WITH|USE)\b",
    re.IGNORECASE,
)


def extract_source_preamble(sql: str) -> tuple[str, str]:
    """Split *sql* into (leading comments/metadata, remainder)."""
    lines = sql.splitlines()
    preamble: list[str] = []
    idx = 0
    in_block = False

    while idx < len(lines):
        line = lines[idx]
        stripped = line.strip()

        if in_block:
            preamble.append(line)
            if "*/" in stripped:
                in_block = False
            idx += 1
            continue

        if stripped.startswith("/*"):
            preamble.append(line)
            if "*/" not in stripped:
                in_block = True
            idx += 1
            continue

        if not stripped:
            preamble.append(line)
            idx += 1
            continue

        if stripped.startswith("--"):
            preamble.append(line)
            idx += 1
            continue

        if re.match(r"^GO\s*$", stripped, re.IGNORECASE):
            preamble.append(line)
            idx += 1
            continue

        if _SQL_START.match(stripped):
            break

        break

    if not preamble:
        return "", sql

    remainder = "\n".join(lines[idx:])
    return "\n".join(preamble).rstrip(), remainder


def attach_source_preamble(preamble: str, converted: str) -> str:
    """Re-attach preserved preamble above converted SQL."""
    if not preamble.strip():
        return converted
    if not converted.strip():
        return preamble
    return f"{preamble.rstrip()}\n\n{converted.lstrip()}"
