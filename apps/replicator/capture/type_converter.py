"""
Module: apps/replicator/capture/type_converter.py
Purpose: Value-level SQL Server to PostgreSQL data type conversion for replication
Author: Migration Platform Team
Created: 2026-05-22
Domain: Replication / Data Mapping
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

logger = logging.getLogger(__name__)

_MONEY_CLEAN = re.compile(r"[$, ]")


@dataclass
class ColumnDef:
    """Describes a single column being replicated with its source type."""

    name: str
    source_type: str


_TYPE_MAP: dict[str, str] = {
    "INT": "INTEGER",
    "BIGINT": "BIGINT",
    "SMALLINT": "SMALLINT",
    "TINYINT": "SMALLINT",
    "BIT": "BOOLEAN",
    "DECIMAL": "NUMERIC",
    "NUMERIC": "NUMERIC",
    "MONEY": "NUMERIC",
    "SMALLMONEY": "NUMERIC",
    "FLOAT": "DOUBLE PRECISION",
    "REAL": "REAL",
    "DATETIME": "TIMESTAMP",
    "DATETIME2": "TIMESTAMP",
    "SMALLDATETIME": "TIMESTAMP",
    "DATE": "DATE",
    "TIME": "TIME",
    "DATETIMEOFFSET": "TIMESTAMPTZ",
    "CHAR": "CHAR",
    "VARCHAR": "VARCHAR",
    "NCHAR": "CHAR",
    "NVARCHAR": "VARCHAR",
    "TEXT": "TEXT",
    "NTEXT": "TEXT",
    "BINARY": "BYTEA",
    "VARBINARY": "BYTEA",
    "IMAGE": "BYTEA",
    "UNIQUEIDENTIFIER": "UUID",
    "XML": "XML",
    "JSON": "JSONB",
    "SQL_VARIANT": "JSONB",
    "ROWVERSION": "BYTEA",
    "TIMESTAMP": "BYTEA",
    "GEOGRAPHY": "GEOGRAPHY",
    "GEOMETRY": "GEOMETRY",
    "HIERARCHYID": "LTREE",
}


@dataclass
class TypeMapping:
    """Maps a source SQL Server type to its PostgreSQL equivalent with converter info."""

    source_type: str
    target_type: str
    needs_conversion: bool = True

    def __post_init__(self) -> None:
        self.needs_conversion = self.source_type != self.target_type

    @staticmethod
    def for_source_type(source_type: str) -> TypeMapping:
        base = _base_type(source_type)
        target = _TYPE_MAP.get(base)
        if target is None:
            return TypeMapping(
                source_type=source_type, target_type=source_type.upper(), needs_conversion=False,
            )
        return TypeMapping(source_type=source_type, target_type=target)

    @staticmethod
    def needs_value_conversion(source_type: str) -> bool:
        base = _base_type(source_type)
        return base in _CONVERTERS


class TypeConverter:
    """Converts individual column values from SQL Server types to PostgreSQL-compatible values.

    Used during data extraction and change event serialization to ensure
    proper formatting for the target database.
    """

    @staticmethod
    def convert(source_type: str, value: Any) -> Any:
        """Convert a single value from SQL Server format to PostgreSQL format.

        Args:
            source_type: SQL Server data type (e.g., 'DATETIME', 'BINARY(256)').
            value: The value to convert.

        Returns:
            Converted value suitable for PostgreSQL insertion.
        """
        if value is None:
            return None

        base = _base_type(source_type)

        converter = TypeConverter._get_converter(base)
        if converter is None:
            return value

        try:
            return converter(value)
        except (ValueError, TypeError) as e:
            logger.warning("Type conversion failed for %s value %r: %s", base, value, e)
            return value

    @staticmethod
    def convert_row(row: dict[str, Any], columns: list[ColumnDef]) -> dict[str, Any]:
        """Convert all values in a row according to column type definitions.

        Args:
            row: Raw row values from SQL Server.
            columns: Column definitions with source types.

        Returns:
            Row with all values converted for PostgreSQL.
        """
        if not columns:
            return row

        col_map = {c.name: c.source_type for c in columns}
        return {
            key: TypeConverter.convert(col_map.get(key, "VARCHAR"), val)
            for key, val in row.items()
        }

    @staticmethod
    def _get_converter(base: str) -> Any | None:
        return _CONVERTERS.get(base)


def _base_type(raw: str) -> str:
    """Extract the base type name, stripping parameters and whitespace."""
    return raw.split("(")[0].split()[0].strip().upper()


def _convert_bit(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    return bool(value)


def _convert_binary(value: Any) -> str:
    raw = bytes(value) if not isinstance(value, (bytes, bytearray)) else bytes(value)
    return "\\x" + raw.hex()


def _convert_uuid(value: Any) -> str:
    if isinstance(value, uuid.UUID):
        return str(value)
    val = str(value).strip().lower()
    try:
        return str(uuid.UUID(val))
    except (ValueError, AttributeError):
        return val


def _convert_datetime(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _convert_date(value: Any) -> str:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, datetime):
        return value.date().isoformat()
    return str(value)


def _convert_time(value: Any) -> str:
    if isinstance(value, time):
        return value.isoformat()
    return str(value)


def _convert_datetimeoffset(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _convert_money(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, Decimal):
        return float(value)
    cleaned = _MONEY_CLEAN.sub("", str(value))
    return float(cleaned)


def _convert_numeric(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


_CONVERTERS: dict[str, Any] = {
    "BIT": _convert_bit,
    "BINARY": _convert_binary,
    "VARBINARY": _convert_binary,
    "IMAGE": _convert_binary,
    "ROWVERSION": _convert_binary,
    "TIMESTAMP": _convert_binary,
    "UNIQUEIDENTIFIER": _convert_uuid,
    "DATETIME": _convert_datetime,
    "DATETIME2": _convert_datetime,
    "SMALLDATETIME": _convert_datetime,
    "DATE": _convert_date,
    "TIME": _convert_time,
    "DATETIMEOFFSET": _convert_datetimeoffset,
    "MONEY": _convert_money,
    "SMALLMONEY": _convert_money,
    "DECIMAL": _convert_numeric,
    "NUMERIC": _convert_numeric,
}
