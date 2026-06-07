"""SQL Server → PostgreSQL DDL types aligned with engine-go ``MapSQLServerType``.

The Go data plane binary COPY encoder uses ``core.LogicalType.PostgresType()``;
target tables must use compatible PostgreSQL types before COPY runs.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

_MAX_LENGTH_SENTINEL = -1


def _base_type_name(type_name: str) -> str:
    base = type_name.strip().lower()
    if "(" in base:
        base = base[: base.index("(")].strip()
    return base


def map_sqlserver_to_postgres_ddl(
    type_name: str,
    *,
    max_length: int | None = None,
    precision: int | None = None,
    scale: int | None = None,
) -> str:
    """Return a PostgreSQL column type string for a SQL Server catalog type."""
    base = _base_type_name(type_name)
    is_max = max_length == _MAX_LENGTH_SENTINEL

    match base:
        case "bit":
            pg = "boolean"
        case "tinyint" | "smallint":
            pg = "smallint"
        case "int":
            pg = "integer"
        case "bigint":
            pg = "bigint"
        case "real":
            pg = "real"
        case "float":
            pg = "double precision"
        case "decimal" | "numeric" | "money" | "smallmoney":
            if precision is not None:
                pg = f"numeric({precision},{scale or 0})"
            else:
                pg = "numeric"
        case "char" | "varchar" | "nchar" | "nvarchar":
            pg = "text" if is_max else "varchar"
        case "text" | "ntext" | "xml":
            pg = "text"
        case "binary" | "varbinary" | "image" | "rowversion" | "timestamp":
            pg = "bytea"
        case "date":
            pg = "date"
        case "time":
            pg = "time"
        case "datetime" | "datetime2" | "smalldatetime":
            pg = "timestamp"
        case "datetimeoffset":
            pg = "timestamptz"
        case "uniqueidentifier":
            pg = "uuid"
        case _:
            pg = "text"

    return pg
