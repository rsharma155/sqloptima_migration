# Author: Ravi Sharma
# Copyright (c) 2026 Ravi Sharma
# SPDX-License-Identifier: MIT

"""Shared kernel: DDL identifier quoting and validation (L-18).

Domain: shared / kernel
Module: shared.kernel.ddl_identifier

This module provides the single source of truth for safely embedding
SQL identifiers into DDL strings.  It must be imported by every domain
layer that generates DDL — DDLGenerator, ProceduralConverter, PostgresConnector.

Key invariants:
  - Identifiers are ALWAYS double-quoted in the output to preserve case and
    allow any printable character (PostgreSQL standard).
  - Embedded double-quote characters are escaped by doubling them
    (e.g. foo"bar → "foo""bar") per SQL-92 / PostgreSQL spec.
  - Empty identifiers and identifiers longer than 63 characters
    (PostgreSQL NAMEDATALEN − 1) are rejected immediately.

Usage::

    from shared.kernel.ddl_identifier import quote_pg_ident, DdlIdentifier

    # Functional style
    ddl = f"CREATE TABLE {quote_pg_ident(schema)}.{quote_pg_ident(table)} ..."

    # Value-object style
    tbl = DdlIdentifier(table_name)
    ddl = f"CREATE TABLE {quote_pg_ident(schema)}.{tbl.quoted} ..."
"""

from __future__ import annotations

from dataclasses import dataclass

# PostgreSQL identifier max length (NAMEDATALEN - 1).
_PG_MAX_IDENTIFIER_LEN = 63


def validate_sql_identifier(name: str, label: str) -> None:
    """Raise ValueError when *name* is not a valid SQL identifier.

    Validation rules (applied to both source and target identifiers):
      - Must be a non-empty string.
      - Must not exceed 63 characters (PostgreSQL NAMEDATALEN − 1).

    The character set is intentionally NOT restricted — PostgreSQL allows any
    Unicode character inside double-quoted identifiers, and we rely on
    double-quoting rather than a character whitelist to prevent injection.

    Args:
        name:  The identifier string to validate.
        label: Human-readable label used in the error message (e.g. "table_name").

    Raises:
        ValueError: If the identifier is empty or too long.
        TypeError:  If *name* is not a string.
    """
    if not isinstance(name, str):
        raise TypeError(f"Identifier {label!r} must be a string, got {type(name).__name__}")
    if not name:
        raise ValueError(f"Identifier {label!r} must not be empty")
    if len(name) > _PG_MAX_IDENTIFIER_LEN:
        raise ValueError(
            f"Identifier {label!r} is {len(name)} characters, "
            f"exceeding the PostgreSQL maximum of {_PG_MAX_IDENTIFIER_LEN}"
        )


def quote_pg_ident(name: str) -> str:
    """Return *name* as a safely double-quoted PostgreSQL identifier.

    Embedded double-quote characters are doubled per SQL-92 rules so that
    the result is always a syntactically valid quoted identifier regardless
    of the input content.

    Args:
        name: Raw identifier string (table name, schema name, column name, …).

    Returns:
        The identifier wrapped in double-quotes with any inner ``"`` escaped.

    Raises:
        ValueError: If *name* is empty.

    Examples::

        >>> quote_pg_ident("orders")
        '"orders"'
        >>> quote_pg_ident('weird"name')
        '"weird""name"'
        >>> quote_pg_ident("Order Details")
        '"Order Details"'
    """
    if not name:
        raise ValueError("Cannot quote an empty identifier")
    # Escape inner double-quotes by doubling them (SQL-92 §5.2).
    escaped = name.replace('"', '""')
    return f'"{escaped}"'


# ═══════════════════════════════════════════════════════════════════════════
# DdlIdentifier — immutable value object (optional; use when type safety helps)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class DdlIdentifier:
    """Immutable, validated PostgreSQL DDL identifier.

    Validated at construction so that any code holding a ``DdlIdentifier``
    is guaranteed to have a non-empty, length-bounded identifier that will
    produce a syntactically correct quoted form.

    Attributes:
        name: The raw (unquoted) identifier string.

    Properties:
        quoted: The identifier wrapped in PostgreSQL double-quotes with any
                embedded ``"`` characters escaped.
    """

    name: str

    def __post_init__(self) -> None:
        validate_sql_identifier(self.name, "DdlIdentifier.name")

    @property
    def quoted(self) -> str:
        """Return the identifier in double-quoted form, inner quotes escaped."""
        return quote_pg_ident(self.name)

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return f"DdlIdentifier({self.name!r})"
