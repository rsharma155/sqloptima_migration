"""Tests for PostgreSQL SSL mode resolution from connection entries."""

from __future__ import annotations

import os

import pytest

from infrastructure.postgres.postgres_connector import (
    postgres_config_from_entry,
    resolve_postgres_ssl_mode,
)


def test_localhost_uses_prefer_without_env():
    assert resolve_postgres_ssl_mode({"host": "localhost"}) == "prefer"


def test_remote_host_requires_tls_by_default():
    assert resolve_postgres_ssl_mode({"host": "db.example.com"}) == "require"


def test_env_override_disable(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MIGRATION_TARGET_SSL_MODE", "disable")
    assert resolve_postgres_ssl_mode({"host": "db.example.com"}) is None


def test_postgres_config_from_entry_applies_ssl_resolution():
    cfg = postgres_config_from_entry(
        {"host": "127.0.0.1", "port": 5432, "database": "target_db", "username": "postgres"},
        password="secret",
    )
    assert cfg.ssl_mode == "prefer"
