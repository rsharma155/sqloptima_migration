"""
Module: shared/kernel/sql_identifier.py
Purpose: Shared SQL identifier validation — reusable across all domains.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import re

# Tight allowlist: letters, digits, underscores, spaces, hyphens.
# Rejects brackets, semicolons, quotes, and all other SQL-injection characters.
_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_ \-]{0,127}$")


def validate_sql_identifier(value: str, label: str) -> None:
    """Raise ValueError if *value* is not a safe SQL identifier.

    Enforces the same allowlist as ``migration_engine._validate_identifier`` so
    that every domain that builds dynamic SQL uses a consistent, injection-safe
    gate.
    """
    if not _IDENTIFIER_RE.match(value):
        raise ValueError(
            f"Invalid SQL identifier for {label!r}: {value!r}. "
            "Must start with a letter or underscore and contain only "
            "alphanumeric characters, underscores, spaces, or hyphens."
        )
