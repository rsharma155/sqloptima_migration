"""Unit tests for automatic PostgreSQL target table provisioning."""

from __future__ import annotations

from domains.migration.go_type_mapping import map_sqlserver_to_postgres_ddl
from application.go_engine_migration.target_table_provisioner import build_create_table_ddl
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
