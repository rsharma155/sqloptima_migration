"""
Module: tests/unit/replicator/test_type_converter.py
Purpose: Unit tests for TypeConverter — value-level SQL Server → PostgreSQL data conversion
Author: Migration Platform Team
Created: 2026-05-22
Domain: Replication / Data Mapping
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

import uuid
from datetime import UTC, date, datetime, time, timedelta, timezone
from decimal import Decimal

from apps.replicator.capture.type_converter import ColumnDef, TypeConverter, TypeMapping


class TestTypeMapping:
    def test_exact_numeric_types(self):
        assert TypeMapping.for_source_type("INT").target_type == "INTEGER"
        assert TypeMapping.for_source_type("BIGINT").target_type == "BIGINT"
        assert TypeMapping.for_source_type("SMALLINT").target_type == "SMALLINT"
        assert TypeMapping.for_source_type("TINYINT").target_type == "SMALLINT"
        assert TypeMapping.for_source_type("BIT").target_type == "BOOLEAN"
        assert TypeMapping.for_source_type("DECIMAL(18,2)").target_type == "NUMERIC"
        assert TypeMapping.for_source_type("MONEY").target_type == "NUMERIC"

    def test_character_types(self):
        assert TypeMapping.for_source_type("VARCHAR(100)").target_type == "VARCHAR"
        assert TypeMapping.for_source_type("NVARCHAR(200)").target_type == "VARCHAR"
        assert TypeMapping.for_source_type("TEXT").target_type == "TEXT"
        assert TypeMapping.for_source_type("NTEXT").target_type == "TEXT"
        assert TypeMapping.for_source_type("CHAR(10)").target_type == "CHAR"
        assert TypeMapping.for_source_type("NCHAR(5)").target_type == "CHAR"

    def test_binary_types(self):
        assert TypeMapping.for_source_type("BINARY").target_type == "BYTEA"
        assert TypeMapping.for_source_type("VARBINARY(MAX)").target_type == "BYTEA"
        assert TypeMapping.for_source_type("IMAGE").target_type == "BYTEA"
        assert TypeMapping.for_source_type("ROWVERSION").target_type == "BYTEA"

    def test_date_time_types(self):
        assert TypeMapping.for_source_type("DATETIME").target_type == "TIMESTAMP"
        assert TypeMapping.for_source_type("DATETIME2").target_type == "TIMESTAMP"
        assert TypeMapping.for_source_type("DATE").target_type == "DATE"
        assert TypeMapping.for_source_type("TIME").target_type == "TIME"
        assert TypeMapping.for_source_type("DATETIMEOFFSET").target_type == "TIMESTAMPTZ"
        assert TypeMapping.for_source_type("SMALLDATETIME").target_type == "TIMESTAMP"

    def test_special_types(self):
        assert TypeMapping.for_source_type("UNIQUEIDENTIFIER").target_type == "UUID"
        assert TypeMapping.for_source_type("XML").target_type == "XML"
        assert TypeMapping.for_source_type("JSON").target_type == "JSONB"
        assert TypeMapping.for_source_type("SQL_VARIANT").target_type == "JSONB"
        assert TypeMapping.for_source_type("FLOAT").target_type == "DOUBLE PRECISION"
        assert TypeMapping.for_source_type("REAL").target_type == "REAL"
        assert TypeMapping.for_source_type("GEOGRAPHY").target_type == "GEOGRAPHY"

    def test_unknown_type_passthrough(self):
        mapping = TypeMapping.for_source_type("CUSTOM_TYPE")
        assert mapping.target_type == "CUSTOM_TYPE"
        assert mapping.needs_conversion is False


class TestTypeConverter:
    def test_convert_bit(self):
        result = TypeConverter.convert("BIT", True)
        assert result is True
        result = TypeConverter.convert("BIT", False)
        assert result is False
        result = TypeConverter.convert("BIT", 1)
        assert result is True
        result = TypeConverter.convert("BIT", 0)
        assert result is False
        result = TypeConverter.convert("BIT", None)
        assert result is None

    def test_convert_int_types(self):
        assert TypeConverter.convert("INT", 42) == 42
        assert TypeConverter.convert("BIGINT", 2**62) == 2**62
        assert TypeConverter.convert("SMALLINT", 32767) == 32767
        assert TypeConverter.convert("TINYINT", 255) == 255
        assert TypeConverter.convert("DECIMAL(18,2)", "123.45") == "123.45"

    def test_convert_money_to_numeric(self):
        assert TypeConverter.convert("MONEY", 123.45) == 123.45
        assert TypeConverter.convert("SMALLMONEY", Decimal("99.99")) == 99.99

    def test_convert_varchar(self):
        assert TypeConverter.convert("VARCHAR(100)", "hello") == "hello"
        assert TypeConverter.convert("NVARCHAR(200)", "unicode") == "unicode"
        assert TypeConverter.convert("TEXT", "long text") == "long text"

    def test_convert_binary_to_hex(self):
        result = TypeConverter.convert("BINARY", b"\x00\x01\x02\xff")
        assert result == "\\x000102ff"
        result = TypeConverter.convert("VARBINARY(MAX)", b"test")
        assert result == "\\x74657374"

    def test_convert_image_to_hex(self):
        result = TypeConverter.convert("IMAGE", b"\x89PNG\r\n")
        assert result.startswith("\\x")

    def test_convert_uniqueidentifier(self):
        u = uuid.UUID("12345678-1234-5678-1234-567812345678")
        result = TypeConverter.convert("UNIQUEIDENTIFIER", u)
        assert result == "12345678-1234-5678-1234-567812345678"

        result = TypeConverter.convert("UNIQUEIDENTIFIER", "12345678-1234-5678-1234-567812345678")
        assert result == "12345678-1234-5678-1234-567812345678"

    def test_convert_datetime_to_iso(self):
        dt = datetime(2026, 5, 22, 14, 30, 0, tzinfo=UTC)
        result = TypeConverter.convert("DATETIME", dt)
        assert "2026-05-22T14:30:00" in result

    def test_convert_datetime_string(self):
        result = TypeConverter.convert("DATETIME", "2026-05-22 14:30:00")
        assert "2026-05-22" in result

    def test_convert_date(self):
        d = date(2026, 5, 22)
        result = TypeConverter.convert("DATE", d)
        assert result == "2026-05-22"

    def test_convert_time(self):
        t = time(14, 30, 0)
        result = TypeConverter.convert("TIME", t)
        assert "14:30:00" in result

    def test_convert_float(self):
        result = TypeConverter.convert("FLOAT", 3.14159)
        assert result == 3.14159

    def test_convert_xml_to_text(self):
        result = TypeConverter.convert("XML", "<root><item/></root>")
        assert result == "<root><item/></root>"

    def test_convert_json(self):
        result = TypeConverter.convert("JSON", '{"key": "value"}')
        assert result == '{"key": "value"}'

    def test_convert_none_returns_none(self):
        assert TypeConverter.convert("INT", None) is None
        assert TypeConverter.convert("VARCHAR(100)", None) is None
        assert TypeConverter.convert("DATETIME", None) is None

    def test_convert_row(self):
        columns = [
            ColumnDef(name="id", source_type="INT"),
            ColumnDef(name="name", source_type="VARCHAR(100)"),
            ColumnDef(name="is_active", source_type="BIT"),
            ColumnDef(name="created_at", source_type="DATETIME"),
        ]
        row = {
            "id": 1, "name": "Alice", "is_active": True,
            "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        }
        converted = TypeConverter.convert_row(row, columns)
        assert converted["id"] == 1
        assert converted["name"] == "Alice"
        assert converted["is_active"] is True
        assert "2026-01-01" in converted["created_at"]

    def test_convert_row_with_unknown_type(self):
        columns = [ColumnDef(name="data", source_type="CUSTOM_TYPE")]
        row = {"data": "raw_value"}
        converted = TypeConverter.convert_row(row, columns)
        assert converted["data"] == "raw_value"

    def test_decimal_conversion(self):
        from decimal import Decimal
        result = TypeConverter.convert("DECIMAL(18,2)", Decimal("123.45"))
        assert result == "123.45"

    def test_binary_large_value(self):
        large = bytes(range(256))
        result = TypeConverter.convert("VARBINARY(MAX)", large)
        assert result.startswith("\\x")
        assert len(result) == 2 + 256 * 2  # \x prefix + 2 hex chars per byte

    def test_rowversion_conversion(self):
        result = TypeConverter.convert("ROWVERSION", b"\x00\x00\x00\x00\x00\x01\x02\x03")
        assert result.startswith("\\x")

    def test_convert_row_empty_columns(self):
        row = {"id": 1, "name": "test"}
        converted = TypeConverter.convert_row(row, [])
        assert converted == row

    def test_convert_float_infinity(self):
        result = TypeConverter.convert("FLOAT", float("inf"))
        assert result == float("inf")

    def test_datetimeoffset_conversion(self):
        dt = datetime(2026, 5, 22, 10, 0, 0, tzinfo=timezone(timedelta(hours=-5)))
        result = TypeConverter.convert("DATETIMEOFFSET", dt)
        assert "2026-05-22T10:00:00" in result
        assert "-05:00" in result or "+00:00" in result

    def test_money_string_input(self):
        result = TypeConverter.convert("MONEY", "$1,234.56")
        assert result == 1234.56

    def test_uniqueidentifier_invalid_string(self):
        result = TypeConverter.convert("UNIQUEIDENTIFIER", "not-a-uuid")
        assert result == "not-a-uuid"  # passthrough for invalid
