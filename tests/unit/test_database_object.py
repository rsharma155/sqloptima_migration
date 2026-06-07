"""
Module: test_database_object.py
Purpose: Unit tests for database object domain models
Author: Migration Platform Team
Created: 2026-05-22
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from uuid import UUID

import pytest

from shared.kernel.database_object import (
    Column,
    DatabaseObject,
    DatabaseObjectType,
    DataType,
    Table,
)


class TestDatabaseObject:
    def test_create_table_object(self):
        obj = DatabaseObject(
            object_type=DatabaseObjectType.TABLE,
            database_name="test_db",
            schema_name="dbo",
            object_name="users",
        )
        assert obj.object_type == DatabaseObjectType.TABLE
        assert obj.database_name == "test_db"
        assert obj.schema_name == "dbo"
        assert obj.object_name == "users"

    def test_fully_qualified_name_auto_generated(self):
        obj = DatabaseObject(
            object_type=DatabaseObjectType.TABLE,
            database_name="test_db",
            schema_name="dbo",
            object_name="users",
        )
        assert obj.fully_qualified_name == "test_db.dbo.users"

    def test_fully_qualified_name_custom(self):
        obj = DatabaseObject(
            object_type=DatabaseObjectType.TABLE,
            database_name="test_db",
            schema_name="dbo",
            object_name="users",
            fully_qualified_name="custom.name",
        )
        assert obj.fully_qualified_name == "custom.name"

    def test_default_compatibility_status(self):
        obj = DatabaseObject(
            object_type=DatabaseObjectType.VIEW,
            database_name="db",
            schema_name="dbo",
            object_name="v1",
        )
        assert obj.compatibility_status.value == "auto_convertible"

    def test_compatibility_notes(self):
        obj = DatabaseObject(
            object_type=DatabaseObjectType.PROCEDURE,
            database_name="db",
            schema_name="dbo",
            object_name="usp_test",
            compatibility_status="partial",
            compatibility_notes=["Dynamic SQL detected", "TVP usage"],
        )
        assert len(obj.compatibility_notes) == 2

    def test_object_id_is_uuid(self):
        obj = DatabaseObject(
            object_type=DatabaseObjectType.TABLE,
            database_name="db",
            schema_name="dbo",
            object_name="t1",
        )
        assert isinstance(obj.id, UUID)


class TestDataType:
    def test_create_simple_type(self):
        dt = DataType(type_name="INT", is_nullable=False)
        assert dt.type_name == "INT"
        assert dt.is_nullable is False

    def test_create_decimal_type(self):
        dt = DataType(type_name="DECIMAL", precision=18, scale=2)
        assert dt.precision == 18
        assert dt.scale == 2

    def test_value_object_immutability(self):
        dt = DataType(type_name="VARCHAR", max_length=100)
        with pytest.raises(Exception):
            dt.type_name = "NVARCHAR"


class TestTable:
    def test_create_table(self):
        table = Table(
            database_name="test_db",
            schema_name="dbo",
            object_name="users",
            row_count_estimate=1000,
        )
        assert table.object_type == DatabaseObjectType.TABLE
        assert table.row_count_estimate == 1000
        assert len(table.columns) == 0

    def test_table_with_columns(self):
        dt1 = DataType(type_name="INT", is_nullable=False)
        dt2 = DataType(type_name="VARCHAR", max_length=100)

        col1 = Column(
            table_id=UUID(int=1),
            column_name="id",
            ordinal_position=1,
            data_type=dt1,
            is_identity=True,
        )
        col2 = Column(
            table_id=UUID(int=1),
            column_name="name",
            ordinal_position=2,
            data_type=dt2,
        )

        table = Table(
            database_name="db",
            schema_name="dbo",
            object_name="users",
            columns=[col1, col2],
        )
        assert len(table.columns) == 2
        assert table.columns[0].is_identity is True

    def test_temporal_table_flag(self):
        table = Table(
            database_name="db",
            schema_name="dbo",
            object_name="audit",
            is_temporal=True,
        )
        assert table.is_temporal is True


class TestColumn:
    def test_create_column(self):
        dt = DataType(type_name="NVARCHAR", max_length=200, is_nullable=True)
        col = Column(
            table_id=UUID(int=1),
            column_name="description",
            ordinal_position=3,
            data_type=dt,
            default_value="N''",
        )
        assert col.column_name == "description"
        assert col.default_value == "N''"
        assert col.is_computed is False

    def test_computed_column(self):
        dt = DataType(type_name="AS", max_length=0)
        col = Column(
            table_id=UUID(int=1),
            column_name="full_name",
            ordinal_position=4,
            data_type=dt,
            is_computed=True,
            computed_definition="(firstName + ' ' + lastName)",
        )
        assert col.is_computed is True
        assert col.computed_definition is not None
