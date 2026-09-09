"""Unit tests for Transfer engine inference, path checks, and preflight compare."""

from __future__ import annotations

from domains.transfer.connection_engine import DatabaseEngine, infer_engine
from domains.transfer.preflight import (
    ColumnInventory,
    ObjectInventory,
    TableInventory,
    compare_table,
    normalize_type,
    summarize_preflight,
)
from domains.transfer.transfer_models import ConnectionEndpoint, same_database
from domains.transfer.transfer_path import TransferPath, validate_path_engines
from domains.licensing.editions import ProductEdition, edition_info
import pytest


def test_infer_engine_from_explicit_field():
    assert infer_engine({"engine": "postgres", "type": "source"}) is DatabaseEngine.POSTGRES
    assert infer_engine({"engine": "sqlserver", "type": "target"}) is DatabaseEngine.SQLSERVER


def test_infer_engine_from_legacy_role():
    assert infer_engine({"type": "source"}) is DatabaseEngine.SQLSERVER
    assert infer_engine({"type": "target"}) is DatabaseEngine.POSTGRES


def test_same_database_rejects_identical_host_port_db():
    a = ConnectionEndpoint(
        connection_id="00000000-0000-0000-0000-000000000001",
        engine="postgres",
        host="db.local",
        port=5432,
        database="sales",
    )
    b = ConnectionEndpoint(
        connection_id="00000000-0000-0000-0000-000000000002",
        engine="postgres",
        host="DB.local",
        port=5432,
        database="SALES",
    )
    assert same_database(a, b)
    b.database = "sales_new"
    assert not same_database(a, b)


def test_validate_path_engines_pg_to_pg():
    validate_path_engines(TransferPath.PG_TO_PG, DatabaseEngine.POSTGRES, DatabaseEngine.POSTGRES)
    with pytest.raises(ValueError, match="pg_to_pg"):
        validate_path_engines(TransferPath.PG_TO_PG, DatabaseEngine.SQLSERVER, DatabaseEngine.POSTGRES)


def test_normalize_type_aliases():
    assert normalize_type("character varying(50)") == "varchar"
    assert normalize_type("INT") == "int"


def test_homogeneous_type_mismatch_is_blocker():
    source = TableInventory(
        schema="public",
        table="orders",
        exists=True,
        row_count=10,
        columns=[ColumnInventory(name="id", type_name="bigint", nullable=False)],
    )
    target = TableInventory(
        schema="public",
        table="orders",
        exists=True,
        columns=[ColumnInventory(name="id", type_name="text", nullable=False)],
    )
    report = compare_table(
        path=TransferPath.PG_TO_PG,
        source=source,
        target=target,
        create_if_missing=False,
        tables_in_job={"public.orders"},
    )
    assert report["has_blocker"]
    assert report["columns"]["type_mismatches"][0]["severity"] == "blocker"


def test_missing_target_table_is_blocker_unless_create():
    source = TableInventory(
        schema="public", table="orders", exists=True,
        columns=[ColumnInventory(name="id", type_name="bigint", nullable=False)],
    )
    missing = TableInventory(schema="public", table="orders", exists=False)
    blocked = compare_table(
        path=TransferPath.PG_TO_PG,
        source=source,
        target=missing,
        create_if_missing=False,
        tables_in_job=set(),
    )
    allowed = compare_table(
        path=TransferPath.PG_TO_PG,
        source=source,
        target=missing,
        create_if_missing=True,
        tables_in_job=set(),
    )
    assert blocked["has_blocker"]
    assert not allowed["has_blocker"]


def test_fk_and_index_recommend_disable():
    source = TableInventory(
        schema="public", table="orders", exists=True,
        columns=[ColumnInventory(name="id", type_name="bigint", nullable=False)],
    )
    target = TableInventory(
        schema="public", table="orders", exists=True,
        columns=[ColumnInventory(name="id", type_name="bigint", nullable=False)],
        indexes=[ObjectInventory(object_id="ix_orders_c", kind="index", extra={"is_primary_key": False})],
        foreign_keys=[ObjectInventory(object_id="orders_fk", kind="foreign_key", extra={"referenced": "public.customers"})],
    )
    report = compare_table(
        path=TransferPath.PG_TO_PG,
        source=source,
        target=target,
        create_if_missing=False,
        tables_in_job={"public.customers"},
    )
    assert report["indexes"][0]["recommended_action"] == "disable"
    assert report["foreign_keys"][0]["referenced_in_job"] is True
    summary = summarize_preflight([report])
    assert summary["can_start"]
    assert summary["warnings"] >= 1


def test_enterprise_edition_includes_transfer(monkeypatch):
    monkeypatch.delenv("MIGRATION_EDITION", raising=False)
    assert "transfer" in edition_info()["features"]
    assert edition_info()["edition"] == ProductEdition.ENTERPRISE.value
