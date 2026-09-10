"""Unit tests for Transfer T-SQL schema clone and create-if-missing DDL."""

from __future__ import annotations

from domains.transfer.preflight import ColumnInventory, TableInventory, compare_table
from domains.transfer.schema_clone import (
    SchemaClonePlan,
    build_add_foreign_key_tsql,
    build_create_index_tsql,
    build_create_schema_tsql,
    build_create_table_pg,
    build_create_table_tsql,
    format_mssql_type,
    split_tsql_batches,
    supports_table_clone,
    supports_tsql_object_clone,
)
from domains.transfer.transfer_path import TransferPath


def test_format_mssql_nvarchar_and_max():
    assert format_mssql_type("nvarchar", max_length=100) == "nvarchar(50)"
    assert format_mssql_type("varchar", max_length=-1) == "varchar(max)"
    assert format_mssql_type("decimal", precision=18, scale=2) == "decimal(18,2)"


def test_create_table_tsql_identity_and_pk():
    sql = build_create_table_tsql(
        schema="dbo",
        table="Orders",
        columns=[
            {
                "name": "OrderId",
                "type_name": "int",
                "nullable": False,
                "is_identity": True,
                "identity_seed": 1,
                "identity_increment": 1,
            },
            {
                "name": "Amount",
                "type_name": "decimal",
                "precision": 12,
                "scale": 2,
                "nullable": False,
            },
        ],
        primary_key_columns=["OrderId"],
        primary_key_name="PK_Orders",
    )
    assert "CREATE TABLE [dbo].[Orders]" in sql
    assert "[OrderId] int IDENTITY(1,1) NOT NULL" in sql
    assert "CONSTRAINT [PK_Orders] PRIMARY KEY ([OrderId])" in sql
    assert "IF OBJECT_ID(N'dbo.Orders', 'U') IS NULL" in sql


def test_create_table_skips_copy_of_computed_via_as_clause():
    sql = build_create_table_tsql(
        schema="dbo",
        table="T",
        columns=[
            {"name": "Id", "type_name": "int", "nullable": False},
            {"name": "FullName", "is_computed": True, "computed_definition": "([First]+[Last])", "is_persisted": True},
        ],
    )
    assert "[FullName] AS ([First]+[Last]) PERSISTED" in sql


def test_index_and_fk_tsql():
    idx = build_create_index_tsql(
        schema="dbo", table="Orders", index_name="IX_Orders_Amount",
        columns=["Amount"], is_unique=False, index_type="NONCLUSTERED",
    )
    assert idx == "CREATE NONCLUSTERED INDEX [IX_Orders_Amount] ON [dbo].[Orders] ([Amount])"
    fk = build_add_foreign_key_tsql(
        schema="dbo", table="Orders", name="FK_Orders_Customer",
        columns=["CustomerId"], referenced_schema="dbo", referenced_table="Customers",
        referenced_columns=["Id"], delete_action="CASCADE",
    )
    assert "FOREIGN KEY ([CustomerId]) REFERENCES [dbo].[Customers] ([Id])" in fk
    assert "ON DELETE CASCADE" in fk


def test_split_go_batches():
    batches = split_tsql_batches("CREATE VIEW v AS SELECT 1 AS x\nGO\nCREATE PROCEDURE p AS BEGIN SELECT 1; END")
    assert len(batches) == 2
    assert batches[0].startswith("CREATE VIEW")
    assert batches[1].startswith("CREATE PROCEDURE")


def test_create_schema_tsql_is_idempotent():
    sql = build_create_schema_tsql("sales")
    assert "sys.schemas" in sql
    assert "CREATE SCHEMA [sales]" in sql


def test_pg_create_table_if_not_exists():
    sql = build_create_table_pg(
        schema="public",
        table="orders",
        columns=[{"name": "id", "pg_type": "bigint", "nullable": False}],
        primary_key_columns=["id"],
    )
    assert sql.startswith('CREATE TABLE IF NOT EXISTS "public"."orders"')
    assert 'PRIMARY KEY ("id")' in sql


def test_path_capabilities():
    assert supports_tsql_object_clone(TransferPath.MSSQL_TO_MSSQL)
    assert not supports_tsql_object_clone(TransferPath.MSSQL_TO_PG)
    assert supports_table_clone(TransferPath.MSSQL_TO_PG)
    assert not supports_table_clone(TransferPath.PG_TO_MSSQL)


def test_preflight_create_if_missing_matches_source_columns():
    source = TableInventory(
        schema="dbo",
        table="orders",
        exists=True,
        columns=[
            ColumnInventory(name="id", type_name="int", nullable=False),
            ColumnInventory(name="full_name", type_name="nvarchar", nullable=True, is_computed=True),
        ],
    )
    missing = TableInventory(schema="dbo", table="orders", exists=False)
    report = compare_table(
        path=TransferPath.MSSQL_TO_MSSQL,
        source=source,
        target=missing,
        create_if_missing=True,
        tables_in_job=set(),
    )
    assert not report["has_blocker"]
    names = [c["name"] for c in report["columns"]["matched"]]
    assert names == ["id"]


def test_schema_clone_plan_roundtrip():
    plan = SchemaClonePlan.from_dict({
        "create_if_missing": True,
        "clone_objects": True,
        "statements": [{
            "phase": "pre_copy",
            "kind": "table",
            "sql": "CREATE TABLE t (id int)",
            "schema": "dbo",
            "name": "t",
            "skip_if_exists": True,
        }],
        "notes": ["n1"],
    })
    assert len(plan.pre_copy()) == 1
    assert plan.to_dict()["statements"][0]["kind"] == "table"
