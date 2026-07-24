"""Privilege hard-fail gate before migration start (§12.6)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_assert_least_privilege_blocks_elevated(monkeypatch):
    from application import migration_service as ms
    from domains.validation.validation_engine import CompatibilityIssue, ValidationSeverity

    monkeypatch.delenv("MIGRATION_ALLOW_ELEVATED_PRIVILEGES", raising=False)

    src = AsyncMock()
    tgt = AsyncMock()
    src.connect = AsyncMock()
    tgt.connect = AsyncMock()
    src.disconnect = AsyncMock()
    tgt.disconnect = AsyncMock()

    async def fake_make(entry):
        return (src if entry["type"] == "source" else tgt), MagicMock()

    monkeypatch.setattr(ms, "make_connector", fake_make)

    with patch(
        "domains.validation.validation_engine.PreMigrationValidator.validate_privileges",
        new=AsyncMock(
            return_value=[
                CompatibilityIssue(
                    severity=ValidationSeverity.BLOCKER,
                    category="privilege",
                    message="Source connection uses sysadmin",
                )
            ]
        ),
    ):
        with pytest.raises(ValueError, match="sysadmin"):
            await ms.assert_least_privilege(
                {"type": "source", "password": "x"},
                {"type": "target", "password": "y"},
            )


@pytest.mark.asyncio
async def test_assert_least_privilege_dev_override(monkeypatch):
    from application import migration_service as ms

    monkeypatch.setenv("MIGRATION_ALLOW_ELEVATED_PRIVILEGES", "1")
    # Should return without connecting
    await ms.assert_least_privilege(
        {"type": "source"},
        {"type": "target"},
    )
