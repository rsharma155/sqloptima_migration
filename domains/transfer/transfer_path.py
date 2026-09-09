"""
Module: transfer_path.py
Purpose: Allowed Cross-Database Transfer engine pairs.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from enum import StrEnum

from domains.transfer.connection_engine import DatabaseEngine


class TransferPath(StrEnum):
    MSSQL_TO_PG = "mssql_to_pg"
    PG_TO_MSSQL = "pg_to_mssql"
    PG_TO_PG = "pg_to_pg"
    MSSQL_TO_MSSQL = "mssql_to_mssql"


PATH_ENGINES: dict[TransferPath, tuple[DatabaseEngine, DatabaseEngine]] = {
    TransferPath.MSSQL_TO_PG: (DatabaseEngine.SQLSERVER, DatabaseEngine.POSTGRES),
    TransferPath.PG_TO_MSSQL: (DatabaseEngine.POSTGRES, DatabaseEngine.SQLSERVER),
    TransferPath.PG_TO_PG: (DatabaseEngine.POSTGRES, DatabaseEngine.POSTGRES),
    TransferPath.MSSQL_TO_MSSQL: (DatabaseEngine.SQLSERVER, DatabaseEngine.SQLSERVER),
}


def is_homogeneous(path: TransferPath) -> bool:
    src, tgt = PATH_ENGINES[path]
    return src is tgt


def engines_for(path: TransferPath) -> tuple[DatabaseEngine, DatabaseEngine]:
    return PATH_ENGINES[path]


def validate_path_engines(
    path: TransferPath,
    source_engine: DatabaseEngine,
    target_engine: DatabaseEngine,
) -> None:
    expected = PATH_ENGINES[path]
    if (source_engine, target_engine) != expected:
        raise ValueError(
            f"Path {path.value} requires source={expected[0].value} and "
            f"target={expected[1].value}, got {source_engine.value} → {target_engine.value}"
        )
