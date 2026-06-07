"""
Module: domains/transpilation/converters/plpgsql/_type_mapper.py
Purpose: Maps T-SQL / SQL Server data types to their PostgreSQL equivalents.
         Used by the header parser (parameter types) and the body transformer
         (DECLARE statement types, temp-table column types).

Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import re
from typing import Optional


# ---------------------------------------------------------------------------
# Type mapping tables
# ---------------------------------------------------------------------------

# T-SQL base type → PostgreSQL base type  (length specifiers handled separately)
_BASE_TYPE_MAP: dict[str, str] = {
    "INT":              "INT",
    "INTEGER":          "INTEGER",
    "BIGINT":           "BIGINT",
    "SMALLINT":         "SMALLINT",
    "TINYINT":          "SMALLINT",
    "BIT":              "BOOLEAN",
    "DECIMAL":          "NUMERIC",
    "NUMERIC":          "NUMERIC",
    "MONEY":            "NUMERIC",
    "SMALLMONEY":       "NUMERIC",
    "FLOAT":            "DOUBLE PRECISION",
    "REAL":             "REAL",
    "CHAR":             "CHAR",
    "VARCHAR":          "VARCHAR",
    "NCHAR":            "CHAR",
    "NVARCHAR":         "VARCHAR",
    "TEXT":             "TEXT",
    "NTEXT":            "TEXT",
    "DATETIME":         "TIMESTAMP",
    "DATETIME2":        "TIMESTAMP",
    "SMALLDATETIME":    "TIMESTAMP",
    "DATE":             "DATE",
    "TIME":             "TIME",
    "DATETIMEOFFSET":   "TIMESTAMPTZ",
    "BINARY":           "BYTEA",
    "VARBINARY":        "BYTEA",
    "IMAGE":            "BYTEA",
    "UNIQUEIDENTIFIER": "UUID",
    "XML":              "XML",
    "JSON":             "JSONB",
    "SQL_VARIANT":      "TEXT",
    "SYSNAME":          "VARCHAR(128)",
    "HIERARCHYID":      "TEXT",   # ⚠️ methods not converted; use ltree extension
    "ROWVERSION":       "BYTEA",
    "CURSOR":           "REFCURSOR",
}

# PG types for which length specifiers must NOT be propagated
# (e.g., TIMESTAMP(3) is valid PG but INT(4) is not)
_NO_LENGTH_TYPES: frozenset[str] = frozenset({
    "TEXT", "INTEGER", "INT", "SMALLINT", "BIGINT", "BOOLEAN", "BYTEA",
    "REFCURSOR", "UUID", "TIMESTAMPTZ", "TIMESTAMP", "DATE", "TIME",
    "DOUBLE PRECISION", "REAL", "NUMERIC", "JSONB",
})


# ---------------------------------------------------------------------------
# TsqlTypeMapper
# ---------------------------------------------------------------------------


class TsqlTypeMapper:
    """Maps T-SQL data types to their PostgreSQL equivalents.

    Usage::

        pg_type = TsqlTypeMapper.map("NVARCHAR(200)")   # → "VARCHAR(200)"
        pg_type = TsqlTypeMapper.map("MONEY")            # → "NUMERIC"
        pg_type = TsqlTypeMapper.map("VARCHAR(MAX)")     # → "TEXT"
    """

    @staticmethod
    def map(tsql_type: str) -> str:
        """Return the PostgreSQL equivalent of a T-SQL data type string.

        Handles:
        - ``VARCHAR(MAX)`` / ``NVARCHAR(MAX)`` → ``TEXT``
        - Preserves length specifiers for types like ``VARCHAR(200)``
        - Drops length specifiers for types where they are invalid in PG
        - Schema-qualified custom types (e.g. ``dbo.MyTableType``)
        """
        t = tsql_type.strip()

        # (N)VARCHAR(MAX) / (N)CHAR(MAX) → TEXT
        if re.match(r'(?:N?VAR)?CHAR\s*\(\s*MAX\s*\)', t, re.IGNORECASE):
            return "TEXT"

        m = re.match(r'(\w+)(\s*\([^)]*\))?', t, re.IGNORECASE)
        if not m:
            return t

        base = m.group(1).upper()
        length_part = (m.group(2) or "").strip()

        pg_base = _BASE_TYPE_MAP.get(base)
        if pg_base is None:
            # Schema-qualified custom type → strip schema, return type name only
            if '.' in t:
                return t.split('.')[-1].strip()
            return t  # unknown type — pass through unchanged

        if pg_base in _NO_LENGTH_TYPES or not length_part:
            return pg_base

        return f"{pg_base}{length_part}"

    @staticmethod
    def map_default(value: Optional[str], tsql_type: str) -> Optional[str]:
        """Convert a T-SQL parameter default value to its PostgreSQL form.

        Currently handles BIT 0/1 → FALSE/TRUE.  All other values are
        returned unchanged.
        """
        if value is None:
            return None
        v = value.strip()
        base_m = re.match(r'(\w+)', tsql_type, re.IGNORECASE)
        base = base_m.group(1).upper() if base_m else ""
        if base == "BIT":
            if v == "0":
                return "FALSE"
            if v == "1":
                return "TRUE"
        return v
