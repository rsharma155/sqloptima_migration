"""Unit tests for pre-migration snapshot gate (§13.3)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from domains.migration.snapshot_gate import SnapshotGate


@pytest.mark.asyncio
async def test_verify_existing_snapshot_file(tmp_path):
    snap = tmp_path / "backup.dump"
    snap.write_bytes(b"fake dump content")
    gate = SnapshotGate()
    result = await gate.verify_or_create(
        AsyncMock(),
        database="testdb",
        tables=["users"],
        existing_ref=str(snap),
    )
    assert result.verified is True


@pytest.mark.asyncio
async def test_missing_snapshot_ref_fails():
    gate = SnapshotGate()
    result = await gate.verify_or_create(
        AsyncMock(),
        database="testdb",
        tables=["users"],
        existing_ref="/nonexistent/snapshot.dump",
    )
    assert result.verified is False


@pytest.mark.asyncio
async def test_snapshot_gate_disabled():
    gate = SnapshotGate()
    result = await gate.verify_or_create(
        AsyncMock(),
        database="testdb",
        tables=["users"],
        require_snapshot=False,
    )
    assert result.verified is True


@pytest.mark.asyncio
async def test_pg_dump_missing_with_override(monkeypatch):
    monkeypatch.delenv("MIGRATION_ALLOW_NO_SNAPSHOT", raising=False)
    gate = SnapshotGate()
    with patch("domains.migration.snapshot_gate.shutil.which", return_value=None):
        result = await gate.verify_or_create(
            AsyncMock(),
            database="testdb",
            tables=["users"],
            require_snapshot=True,
        )
    assert result.verified is False

    monkeypatch.setenv("MIGRATION_ALLOW_NO_SNAPSHOT", "1")
    with patch("domains.migration.snapshot_gate.shutil.which", return_value=None):
        result = await gate.verify_or_create(
            AsyncMock(),
            database="testdb",
            tables=["users"],
            require_snapshot=True,
        )
    assert result.verified is True
    assert "override" in result.message.lower()
