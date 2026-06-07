"""Unit tests for post-cutover connection switch manifest (§13.2)."""
from __future__ import annotations

from domains.orchestration.connection_switch import ConnectionSwitchService


def test_build_manifest_contains_dsns_and_instructions():
    manifest = ConnectionSwitchService.build_manifest(
        job_id="job-abc",
        source_cfg={
            "host": "sql.example.com",
            "port": 1433,
            "database": "OrdersDB",
            "username": "sa",
        },
        target_cfg={
            "host": "pg.example.com",
            "port": 5432,
            "database": "orders",
            "username": "app",
        },
        tables=["users", "orders"],
        target_schema="app_schema",
    )
    assert manifest.job_id == "job-abc"
    assert "sql.example.com" in manifest.source_dsn
    assert "pg.example.com" in manifest.target_dsn
    assert "app_schema" in manifest.target_dsn
    assert manifest.target_schema == "app_schema"
    assert manifest.tables == ["users", "orders"]
    assert len(manifest.instructions) >= 4
    assert manifest.committed_at
