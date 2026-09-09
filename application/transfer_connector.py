"""
Module: transfer_connector.py
Purpose: Open a SQL Server or PostgreSQL connector from engine, not role.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from typing import Any

from domains.transfer.connection_engine import DatabaseEngine, infer_engine


async def make_transfer_connector(entry: dict) -> tuple[Any, Any]:
    """Build a connector using ``engine`` (sqlserver|postgres), never role."""
    from application.migration_service import _decrypt_password

    password = _decrypt_password(entry)
    engine = infer_engine(entry)
    if engine is DatabaseEngine.SQLSERVER:
        from infrastructure.sqlserver.sqlserver_connector import (
            SqlServerConnector,
            sqlserver_config_from_entry,
        )

        config = sqlserver_config_from_entry(entry, password=password)
        return SqlServerConnector(config), config

    from infrastructure.postgres.postgres_connector import (
        PostgresConnector,
        postgres_config_from_entry,
    )

    config = postgres_config_from_entry(entry, password=password)
    return PostgresConnector(config), config
