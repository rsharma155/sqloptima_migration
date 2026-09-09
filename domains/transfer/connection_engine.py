"""
Module: connection_engine.py
Purpose: Database engine identity separate from connection role (source/target).
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from enum import StrEnum


class DatabaseEngine(StrEnum):
    SQLSERVER = "sqlserver"
    POSTGRES = "postgres"


def infer_engine(entry: dict) -> DatabaseEngine:
    """Resolve engine from explicit field, then role, then port.

    Existing connections store role in ``type`` / ``db_type`` (source|target),
    not the RDBMS. Missing engine is inferred so Migrations keep working.
    """
    raw = str(entry.get("engine") or "").strip().lower()
    if raw in {"sqlserver", "mssql"}:
        return DatabaseEngine.SQLSERVER
    if raw in {"postgres", "postgresql", "pg"}:
        return DatabaseEngine.POSTGRES

    role = str(entry.get("type") or entry.get("db_type") or "").strip().lower()
    if role == "source":
        return DatabaseEngine.SQLSERVER
    if role == "target":
        return DatabaseEngine.POSTGRES

    try:
        port = int(entry.get("port") or 0)
    except (TypeError, ValueError):
        port = 0
    if port == 1433:
        return DatabaseEngine.SQLSERVER
    if port == 5432:
        return DatabaseEngine.POSTGRES

    raise ValueError("Cannot infer database engine; set engine to sqlserver or postgres")


def default_port(engine: DatabaseEngine) -> int:
    return 1433 if engine is DatabaseEngine.SQLSERVER else 5432


def default_schema(engine: DatabaseEngine) -> str:
    return "dbo" if engine is DatabaseEngine.SQLSERVER else "public"
