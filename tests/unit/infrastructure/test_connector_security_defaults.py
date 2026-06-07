"""
Module: tests/unit/infrastructure/test_connector_security_defaults.py
Purpose: TDD tests for DBA feedback security fixes:
         8.1 — TrustServerCertificate must default to False.
         8.2 — PostgreSQL ssl_mode must default to "require".
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import pytest

from infrastructure.postgres.postgres_connector import PostgresConnectionConfig
from infrastructure.sqlserver.sqlserver_connector import SqlServerConnectionConfig


class TestSqlServerTlsDefault:
    """
    Issue 8.1: trust_server_certificate must default to False so production
    deployments are secure by default, not by opt-out.
    """

    def test_trust_server_certificate_defaults_to_false(self):
        config = SqlServerConnectionConfig(
            host="sql-server", port=1433, database="mydb",
            username="sa", password="pass",
        )
        assert config.trust_server_certificate is False, (
            "trust_server_certificate must default to False (secure by default). "
            "Fix 8.1 not applied."
        )

    def test_connection_string_has_no_trustservercertificate_yes_by_default(self):
        config = SqlServerConnectionConfig(
            host="sql-server", port=1433, database="mydb",
            username="sa", password="pass",
        )
        cs = config.connection_string
        assert "TrustServerCertificate=no" in cs or "TrustServerCertificate=No" in cs, (
            f"Default connection string must NOT trust certificate: {cs!r}"
        )

    def test_trust_can_be_explicitly_enabled_for_dev(self):
        """Allow opt-in for development/test environments."""
        config = SqlServerConnectionConfig(
            host="localhost", port=1433, database="devdb",
            username="dev", password="dev",
        )
        config.trust_server_certificate = True  # class attribute override for dev
        assert config.trust_server_certificate is True
        cs = config.connection_string
        assert "TrustServerCertificate=yes" in cs or "TrustServerCertificate=Yes" in cs


class TestPostgresSslModeDefault:
    """
    Issue 8.2: PostgreSQL ssl_mode must default to "require" to enforce TLS,
    not None (opportunistic/plaintext fallback).
    """

    def test_ssl_mode_defaults_to_require(self):
        config = PostgresConnectionConfig(
            host="pg-host", port=5432, database="mydb",
            username="user", password="pass",
        )
        assert config.ssl_mode == "require", (
            f"ssl_mode must default to 'require' for secure-by-default TLS. "
            f"Got: {config.ssl_mode!r}. Fix 8.2 not applied."
        )

    def test_ssl_mode_can_be_set_to_none_for_local_dev(self):
        config = PostgresConnectionConfig(
            host="localhost", port=5432, database="devdb",
            username="dev", password="dev",
        )
        config.ssl_mode = None  # class attribute override for local dev
        assert config.ssl_mode is None

    def test_ssl_mode_verify_full_accepted(self):
        config = PostgresConnectionConfig(
            host="pg.prod.internal", port=5432, database="prod",
            username="svc", password="secret",
        )
        config.ssl_mode = "verify-full"
        assert config.ssl_mode == "verify-full"
