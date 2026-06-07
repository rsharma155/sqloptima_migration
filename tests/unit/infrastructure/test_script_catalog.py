"""Tests for infrastructure/sql_scripts/script_catalog.py."""

from __future__ import annotations

from infrastructure.sql_scripts.script_catalog import get_privilege_script_bundle


def test_privilege_script_bundle_includes_source_and_target():
    bundle = get_privilege_script_bundle()

    assert "source" in bundle
    assert "target" in bundle

    source = bundle["source"]
    assert source["engine"] == "sqlserver"
    assert "001_create_source_migration_user.sql" in source["file"]
    assert "CREATE LOGIN" in source["content"]
    assert "db_datareader" in source["content"]
    assert source["recommended_login"] == "migration_reader"
    assert "VIEW DEFINITION" in source["privileges"]

    target = bundle["target"]
    assert target["engine"] == "postgresql"
    assert "002_create_target_migration_user.sql" in target["file"]
    assert "CREATE ROLE" in target["content"]
    assert target["recommended_role"] == "migration_writer"
    assert "CONNECT on target database" in target["privileges"]
