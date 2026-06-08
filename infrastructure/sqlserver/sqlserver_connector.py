"""
Module: sqlserver_connector.py
Purpose: SQL Server database connector using pyodbc (thread-pool safe)
Author: Migration Platform Team
Created: 2026-05-22
Domain: Infrastructure
Dependencies: pyodbc
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

import asyncio
from typing import Any

import pyodbc

from shared.contracts.base_connector import ConnectionConfig, DatabaseConnector
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)

class SqlServerConnectionConfig(ConnectionConfig):
    """Connection configuration for SQL Server.

    Security note: ``trust_server_certificate=True`` means the connection is
    encrypted but the server certificate is NOT verified.  An attacker on the
    same network can present any certificate and intercept all traffic (MITM).
    Set ``trust_server_certificate=False`` in production and configure a
    CA-signed certificate on the SQL Server.
    """

    def __init__(
        self,
        host: str,
        port: int,
        database: str,
        username: str,
        password: str,
        schema: str | None = None,
        extra_params: dict[str, str] | None = None,
        driver: str = "{ODBC Driver 18 for SQL Server}",
        # Fix 8.1: default to False (secure by default).  Set to True only for
        # development/test environments where the SQL Server has a self-signed cert.
        trust_server_certificate: bool = False,
    ) -> None:
        super().__init__(
            host=host,
            port=port,
            database=database,
            username=username,
            password=password,
            schema=schema,
            extra_params=extra_params,
        )
        self.driver = driver
        self.trust_server_certificate = trust_server_certificate

    @property
    def connection_string(self) -> str:
        params = (
            f"DRIVER={self.driver};"
            f"SERVER={self.host},{self.port};"
            f"DATABASE={self.database};"
            f"UID={self.username};"
        )
        # Password passed separately to avoid logging exposure
        if self.password:
            params += f"PWD={self.password};"
        params += f"TrustServerCertificate={'yes' if self.trust_server_certificate else 'no'};"
        for key, value in self.extra_params.items():
            params += f"{key}={value};"
        return params

    @property
    def dsn(self) -> str:
        """Return a DSN string without password for logging."""
        return (
            f"DRIVER={self.driver};"
            f"SERVER={self.host},{self.port};"
            f"DATABASE={self.database};"
            f"UID={self.username};"
            f"TrustServerCertificate={'yes' if self.trust_server_certificate else 'no'};"
        )


def trust_server_certificate_from_mapping(entry: dict) -> bool:
    """Return whether ODBC should trust the SQL Server TLS certificate."""
    if entry.get("trust_server_certificate") is not None:
        return bool(entry["trust_server_certificate"])
    return bool(entry.get("ssl_enabled", False))


def sqlserver_config_from_entry(entry: dict, *, password: str) -> SqlServerConnectionConfig:
    """Build a SQL Server config from a connection-store entry dict."""
    return SqlServerConnectionConfig(
        host=entry["host"],
        port=int(entry.get("port", 1433)),
        database=entry["database"],
        username=entry.get("username", ""),
        password=password,
        schema=entry.get("schema", "dbo"),
        trust_server_certificate=trust_server_certificate_from_mapping(entry),
    )


def sqlserver_config_from_resolved(
    cfg: dict,
    *,
    password: str,
    schema: str | None = None,
) -> SqlServerConnectionConfig:
    """Build a SQL Server config from WorkflowBridgeService.resolve_connection()."""
    return SqlServerConnectionConfig(
        host=cfg["host"],
        port=int(cfg.get("port", 1433)),
        database=cfg["database"],
        username=cfg.get("username", ""),
        password=password,
        schema=schema or cfg.get("schema", "dbo"),
        trust_server_certificate=trust_server_certificate_from_mapping(cfg),
    )


class SqlServerConnector(DatabaseConnector):
    """SQL Server connector implementing DatabaseConnector port."""

    def __init__(self, config: SqlServerConnectionConfig):
        self._config = config
        self._connection: pyodbc.Connection | None = None
        self._cursor: pyodbc.Cursor | None = None

    async def connect(self) -> None:
        if self._connection is not None:
            return
        dsn = self._config.dsn
        logger.debug("Connecting to SQL Server", dsn=dsn)
        try:
            loop = asyncio.get_running_loop()
            self._connection = await loop.run_in_executor(
                None, pyodbc.connect, self._config.connection_string
            )
            self._cursor = self._connection.cursor()
            logger.debug("Connected to SQL Server", database=self._config.database)
        except Exception as exc:
            logger.error("Failed to connect to SQL Server", dsn=dsn, error=str(exc))
            raise

    async def disconnect(self) -> None:
        if self._cursor:
            self._cursor.close()
        if self._connection:
            logger.debug("Disconnecting from SQL Server", database=self._config.database)
            self._connection.close()

    async def execute(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if not self._cursor:
            raise RuntimeError("Not connected. Call connect() first.")
        loop = asyncio.get_running_loop()
        try:
            def _sync_execute() -> list[dict[str, Any]]:
                # pyodbc treats ``execute(sql, None)`` as a single NULL parameter,
                # not "no parameters" — which makes a marker-less query raise
                # "0 parameter markers, but 1 parameters were supplied". Only pass
                # a parameter sequence when we actually have parameters.
                if params:
                    self._cursor.execute(query, tuple(params.values()))
                else:
                    self._cursor.execute(query)
                columns = [column[0] for column in self._cursor.description] if self._cursor.description else []
                return [
                    dict(zip(columns, row, strict=False))
                    for row in self._cursor.fetchall()
                ]
            return await loop.run_in_executor(None, _sync_execute)
        except Exception as exc:
            logger.error("SQL Server query failed", error=str(exc))
            raise

    async def execute_many(self, query: str, params_list: list[dict[str, Any]]) -> None:
        if not self._cursor:
            raise RuntimeError("Not connected. Call connect() first.")
        loop = asyncio.get_running_loop()
        try:
            def _sync_execute_many() -> None:
                self._cursor.executemany(query, [tuple(p.values()) for p in params_list])
                self._connection.commit()
            await loop.run_in_executor(None, _sync_execute_many)
        except Exception as exc:
            logger.error("SQL Server execute_many failed", error=str(exc))
            raise

    @property
    def connection(self) -> pyodbc.Connection | None:
        return self._connection
