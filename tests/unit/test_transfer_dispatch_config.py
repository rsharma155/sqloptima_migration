"""Unit tests for TransferDispatchConfig (control plane → Go data plane)."""

from __future__ import annotations

from uuid import UUID

import pytest

from domains.transfer.transfer_dispatch_config import (
    TransferConnectionRef,
    TransferDispatchConfig,
    TransferTablePayload,
    build_transfer_dispatch_config,
)
from domains.transfer.transfer_path import TransferPath

JOB_ID = UUID("550e8400-e29b-41d4-a716-446655440000")
SRC = UUID("550e8400-e29b-41d4-a716-446655440001")
TGT = UUID("550e8400-e29b-41d4-a716-446655440002")


def _valid() -> TransferDispatchConfig:
    return TransferDispatchConfig(
        job_id=JOB_ID,
        path=TransferPath.PG_TO_PG,
        source=TransferConnectionRef(connection_id=SRC, schema="public", engine="postgres"),
        target=TransferConnectionRef(connection_id=TGT, schema="public", engine="postgres"),
        tables=(
            TransferTablePayload(
                source_schema="public",
                source_table="orders",
                target_schema="public",
                target_table="orders",
                columns=("id", "amount"),
                chunk_size=10_000,
                order_column="id",
                row_count_estimate=100,
            ),
        ),
        constraint_plan={"on_stop": "restore_now", "tables": {}},
    )


def test_to_dict_kind_is_transfer_not_migration_executor():
    data = _valid().to_dict()
    assert data["kind"] == "transfer"
    assert data["path"] == "pg_to_pg"
    assert "executor" not in data
    assert data["tables"][0]["columns"] == ["id", "amount"]


def test_from_dict_round_trip():
    original = _valid()
    restored = TransferDispatchConfig.from_dict(original.to_dict())
    assert restored == original


def test_validate_rejects_empty_tables():
    cfg = _valid()
    bad = TransferDispatchConfig(
        job_id=cfg.job_id,
        path=cfg.path,
        source=cfg.source,
        target=cfg.target,
        tables=(),
    )
    with pytest.raises(ValueError, match="at least one table"):
        bad.validate()


def test_validate_rejects_wildcard_columns():
    cfg = _valid()
    table = cfg.tables[0]
    bad_table = TransferTablePayload(
        source_schema=table.source_schema,
        source_table=table.source_table,
        target_schema=table.target_schema,
        target_table=table.target_table,
        columns=("*",),
        chunk_size=table.chunk_size,
    )
    bad = TransferDispatchConfig(
        job_id=cfg.job_id,
        path=cfg.path,
        source=cfg.source,
        target=cfg.target,
        tables=(bad_table,),
    )
    with pytest.raises(ValueError, match="wildcard"):
        bad.validate()


def test_from_dict_rejects_migration_kind():
    with pytest.raises(ValueError, match="kind"):
        TransferDispatchConfig.from_dict({"kind": "go", "job_id": str(JOB_ID), "path": "pg_to_pg", "tables": []})


def test_build_transfer_dispatch_config_fills_columns_from_preflight():
    tables = [
        {
            "source_schema": "public",
            "source_table": "orders",
            "target_schema": "sales",
            "target_table": "orders",
            "columns": [],
            "row_count_estimate": 50,
        }
    ]
    preflight = {
        "tables": [
            {
                "source": {"schema": "public", "table": "orders"},
                "columns": {
                    "matched": [
                        {"name": "id", "source_type": "bigint", "target_type": "bigint"},
                        {"name": "amount", "source_type": "numeric", "target_type": "numeric"},
                    ]
                },
            }
        ]
    }
    cfg = build_transfer_dispatch_config(
        job_id=JOB_ID,
        path=TransferPath.PG_TO_PG,
        source_connection_id=SRC,
        target_connection_id=TGT,
        source_engine="postgres",
        target_engine="postgres",
        tables=tables,
        threshold={"chunk_size": 25000},
        constraint_plan={"on_stop": "restore_now"},
        preflight=preflight,
    )
    assert cfg.tables[0].columns == ("id", "amount")
    assert cfg.tables[0].chunk_size == 25000
    assert cfg.file_offload["enabled"] is True
    assert cfg.file_offload["min_rows"] == 2_000_000
    cfg.validate()


def test_dispatch_config_snapshots_custom_file_offload():
    cfg = build_transfer_dispatch_config(
        job_id=JOB_ID,
        path=TransferPath.PG_TO_PG,
        source_connection_id=SRC,
        target_connection_id=TGT,
        source_engine="postgres",
        target_engine="postgres",
        tables=[
            {
                "source_schema": "public",
                "source_table": "orders",
                "target_schema": "public",
                "target_table": "orders",
                "columns": ["id"],
            }
        ],
        threshold={"chunk_size": 1000},
        constraint_plan={},
        preflight=None,
        file_offload={"enabled": False, "min_rows": 5_000_000, "min_mb": 512.0, "staging_path": "D:/offload"},
    )
    data = cfg.to_dict()
    assert data["file_offload"] == {
        "enabled": False,
        "min_rows": 5_000_000,
        "min_mb": 512.0,
        "staging_path": "D:/offload",
    }
