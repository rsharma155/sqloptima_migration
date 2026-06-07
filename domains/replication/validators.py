"""
Module: validators.py
Purpose: Strict identifier validation for replication (SQL injection prevention)
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import re

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def validate_identifier(value: str) -> str:
    """Validate a SQL identifier (schema, table, column).

    Raises:
        ValueError: If the identifier is empty or contains unsafe characters.
    """
    trimmed = value.strip()
    if not trimmed or not _IDENTIFIER_RE.match(trimmed):
        raise ValueError(f"invalid SQL identifier: {value!r}")
    return trimmed


def validate_table_list(tables: list[str]) -> list[str]:
    """Validate and deduplicate table names preserving first-seen casing."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in tables:
        name = validate_identifier(raw)
        key = name.lower()
        if key not in seen:
            seen.add(key)
            out.append(name)
    if not out:
        raise ValueError("at least one table is required")
    return out
