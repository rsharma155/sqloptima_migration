"""Tests for product editions (§13.8)."""
from domains.licensing.editions import ProductEdition, current_edition, edition_info


def test_default_enterprise_edition(monkeypatch):
    monkeypatch.delenv("MIGRATION_EDITION", raising=False)
    info = edition_info()
    assert info["edition"] == ProductEdition.ENTERPRISE.value
    assert "programs" in info["features"]


def test_assess_edition_limits_features(monkeypatch):
    monkeypatch.setenv("MIGRATION_EDITION", "assess")
    assert current_edition() == ProductEdition.ASSESS
    assert "migration" not in edition_info()["features"]
