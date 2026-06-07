"""
Module: test_target_table_provisioner.py
Purpose: Unit tests for automatic PostgreSQL target table provisioning.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from domains.migration.go_type_mapping import map_sqlserver_to_postgres_ddl
from application.go_engine_migration.target_table_provisioner import (
    MIGRATION_LOAD_DDL_POLICY,
    build_create_table_ddl,
)
from shared.kernel.database_object import Column, DataType, Table


def test_map_sqlserver_decimal_preserves_precision():
    assert map_sqlserver_to_postgres_ddl("decimal", precision=18, scale=2) == "numeric(18,2)"


def test_map_sqlserver_nvarchar_max_becomes_text():
    assert map_sqlserver_to_postgres_ddl("nvarchar", max_length=-1) == "text"


def test_build_create_table_ddl_quotes_mixed_case_identifiers():
    table = Table(
        database_name="AppDb",
        schema_name="dbo",
        object_name="SystemLogs",
        columns=[
            Column(
                table_id=None,  # type: ignore[arg-type]
                column_name="LogId",
                ordinal_position=1,
                data_type=DataType(type_name="int", is_nullable=False),
                is_nullable=False,
            ),
            Column(
                table_id=None,  # type: ignore[arg-type]
                column_name="Message",
                ordinal_position=2,
                data_type=DataType(type_name="nvarchar", max_length=-1, is_nullable=True),
                is_nullable=True,
            ),
        ],
    )
    ddl = build_create_table_ddl(table, target_schema="public", pk_columns=["LogId"])
    assert 'CREATE TABLE IF NOT EXISTS "public"."SystemLogs"' in ddl
    assert '"LogId" integer NOT NULL' in ddl
    assert '"Message" text' in ddl
    assert 'PRIMARY KEY ("LogId")' in ddl


def test_build_create_table_ddl_applies_column_type_overrides():
    table = Table(
        database_name="AppDb",
        schema_name="dbo",
        object_name="dt_MiscTypes",
        columns=[
            Column(
                table_id=None,  # type: ignore[arg-type]
                column_name="col_hierarchyid",
                ordinal_position=1,
                data_type=DataType(type_name="hierarchyid"),
                is_nullable=True,
            ),
        ],
    )
    ddl = build_create_table_ddl(
        table,
        target_schema="public",
        column_pg_types={"col_hierarchyid": "ltree"},
    )
    assert '"col_hierarchyid" ltree' in ddl


def test_migration_load_schema_excludes_identity_defaults_and_indexes():
    table = Table(
        database_name="AppDb",
        schema_name="dbo",
        object_name="Hotels",
        columns=[
            Column(
                table_id=None,  # type: ignore[arg-type]
                column_name="HotelID",
                ordinal_position=1,
                data_type=DataType(type_name="int", is_nullable=False),
                is_nullable=False,
                is_identity=True,
                default_value="(getdate())",
            ),
            Column(
                table_id=None,  # type: ignore[arg-type]
                column_name="HotelName",
                ordinal_position=2,
                data_type=DataType(type_name="nvarchar", max_length=400, is_nullable=True),
                is_nullable=True,
            ),
        ],
    )
    ddl = build_create_table_ddl(table, target_schema="public", pk_columns=["HotelID"])
    assert MIGRATION_LOAD_DDL_POLICY in (
        "minimal_load",
    )
    assert "GENERATED" not in ddl
    assert "IDENTITY" not in ddl
    assert "SERIAL" not in ddl
    assert "DEFAULT" not in ddl
    assert "CREATE INDEX" not in ddl
    assert 'PRIMARY KEY ("HotelID")' in ddl
