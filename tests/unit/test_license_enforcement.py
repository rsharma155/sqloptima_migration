"""License key validation tests (§13.8)."""
from __future__ import annotations

import pytest

from domains.licensing.editions import ProductEdition
from domains.licensing.license_enforcement import (
    generate_license_key,
    validate_license_key,
)


def test_dev_local_license_allowed_outside_production(monkeypatch):
    monkeypatch.delenv("MIGRATION_LICENSE_KEY", raising=False)
    monkeypatch.delenv("MIGRATION_ENV", raising=False)
    ok, msg = validate_license_key()
    assert ok
    assert "development" in msg


def test_dev_local_rejected_in_production(monkeypatch):
    monkeypatch.setenv("MIGRATION_LICENSE_KEY", "DEV-LOCAL")
    monkeypatch.setenv("MIGRATION_ENV", "production")
    ok, _ = validate_license_key()
    assert not ok


def test_generated_key_matches_edition(monkeypatch):
    monkeypatch.setenv("MIGRATION_EDITION", "migrate")
    monkeypatch.setenv("MIGRATION_LICENSE_SECRET", "test-secret")
    key = generate_license_key(ProductEdition.MIGRATE)
    monkeypatch.setenv("MIGRATION_LICENSE_KEY", key)
    ok, msg = validate_license_key()
    assert ok
    assert "migrate" in msg
