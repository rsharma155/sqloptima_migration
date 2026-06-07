"""
Module: tests/unit/test_config_validation.py
Purpose: Unit tests for connection-config validation helpers (Issue #27).
Domain: Contracts
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import pytest

from shared.contracts.config_validation import validate_pool_bounds, validate_port


class TestValidatePort:
    @pytest.mark.parametrize("port", [1, 1433, 5432, 65535])
    def test_accepts_valid_ports(self, port):
        validate_port(port)  # must not raise

    @pytest.mark.parametrize("port", [0, -1, 65536, 99999])
    def test_rejects_out_of_range_ports(self, port):
        with pytest.raises(ValueError, match="port"):
            validate_port(port)


class TestValidatePoolBounds:
    def test_accepts_valid_bounds(self):
        validate_pool_bounds(2, 20)

    def test_accepts_equal_bounds(self):
        validate_pool_bounds(5, 5)

    def test_rejects_min_below_one(self):
        with pytest.raises(ValueError):
            validate_pool_bounds(0, 10)

    def test_rejects_max_below_min(self):
        with pytest.raises(ValueError, match="max"):
            validate_pool_bounds(10, 5)


class TestConnectionConfigWiring:
    """The validators must actually be enforced by the config/connector classes."""

    def test_connection_config_rejects_bad_port(self):
        from infrastructure.sqlserver.sqlserver_connector import SqlServerConnectionConfig

        with pytest.raises(ValueError, match="port"):
            SqlServerConnectionConfig(
                host="localhost", port=0, database="db",
                username="sa", password="pw",
            )

    def test_connection_config_accepts_valid_port(self):
        from infrastructure.sqlserver.sqlserver_connector import SqlServerConnectionConfig

        cfg = SqlServerConnectionConfig(
            host="localhost", port=1433, database="db",
            username="sa", password="pw",
        )
        assert cfg.port == 1433

    @pytest.mark.asyncio
    async def test_postgres_connect_rejects_bad_pool_bounds(self):
        from infrastructure.postgres.postgres_connector import (
            PostgresConnectionConfig,
            PostgresConnector,
        )

        cfg = PostgresConnectionConfig(
            host="localhost", port=5432, database="db",
            username="u", password="pw",
        )
        # Force an invalid pool configuration; connect() must reject it BEFORE
        # attempting any network I/O.
        cfg.min_pool_size = 30
        cfg.max_pool_size = 20
        connector = PostgresConnector(cfg)
        with pytest.raises(ValueError, match="pool"):
            await connector.connect()
