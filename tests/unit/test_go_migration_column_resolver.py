"""Unit tests for Go dispatch column/type resolution."""

from __future__ import annotations

from shared.kernel.database_object import Column, DataType
from application.go_engine_migration.go_migration_column_resolver import (
    format_sqlserver_column_type,
)


def test_format_sqlserver_nvarchar_max():
    col = Column(
        table_id=None,  # type: ignore[arg-type]
        column_name="Notes",
        ordinal_position=1,
        data_type=DataType(type_name="nvarchar", max_length=-1),
    )
    assert format_sqlserver_column_type(col) == "nvarchar(max)"


def test_format_sqlserver_decimal_with_scale():
    col = Column(
        table_id=None,  # type: ignore[arg-type]
        column_name="Amount",
        ordinal_position=1,
        data_type=DataType(type_name="decimal", precision=18, scale=2),
    )
    assert format_sqlserver_column_type(col) == "decimal(18,2)"


def test_format_sqlserver_int():
    col = Column(
        table_id=None,  # type: ignore[arg-type]
        column_name="BookingId",
        ordinal_position=1,
        data_type=DataType(type_name="int"),
    )
    assert format_sqlserver_column_type(col) == "int"
