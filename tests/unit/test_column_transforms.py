"""Unit tests for column transform pipeline and PII masking (§12.2)."""
from __future__ import annotations

from domains.migration.column_transforms import (
    BUILT_IN_TRANSFORMS,
    ColumnTransformPipeline,
    build_pipeline_for_plan,
    mask_hash,
    mask_last_four,
    mask_nullify,
    mask_partial_email,
)


def test_bit_to_bool_transform():
    pipeline = ColumnTransformPipeline()
    pipeline.register("active", "bit_to_bool")
    row = pipeline.apply({"active": 1, "name": "Alice"})
    assert row["active"] is True
    assert row["name"] == "Alice"


def test_mask_hash_is_deterministic():
    h1 = mask_hash("secret@email.com")
    h2 = mask_hash("secret@email.com")
    assert h1 == h2
    assert len(h1) == 64


def test_mask_nullify():
    assert mask_nullify("anything") is None
    assert mask_nullify(None) is None


def test_mask_partial_email():
    assert mask_partial_email("john.doe@example.com") == "j***@example.com"


def test_mask_last_four():
    assert mask_last_four("4111111111111111") == "****1111"


def test_from_sensitivity_map_applies_defaults():
    pipeline = ColumnTransformPipeline.from_sensitivity_map({
        "email": "pii",
        "ssn": "pii",
        "card_number": "pci",
        "password_hash": "credential",
    })
    row = pipeline.apply({
        "email": "a@b.com",
        "ssn": "123-45-6789",
        "card_number": "4111111111111111",
        "password_hash": "sekret",
        "qty": 5,
    })
    assert row["email"] != "a@b.com"
    assert row["ssn"] != "123-45-6789"
    assert row["card_number"] != "4111111111111111"
    assert len(str(row["card_number"])) == len("4111111111111111")
    assert row["password_hash"] is None
    assert row["qty"] == 5


def test_build_pipeline_for_plan_composes_type_and_mask():
    pipeline = build_pipeline_for_plan(
        column_types={"is_active": "bit"},
        column_sensitivity={"email": "pii"},
    )
    assert pipeline is not None
    row = pipeline.apply({"is_active": 0, "email": "x@y.com"})
    assert row["is_active"] is False
    assert row["email"] != "x@y.com"


def test_mask_fpe_numeric_preserves_length():
    from domains.migration.column_transforms import mask_fpe_numeric

    original = "4111-1111-1111-1111"
    masked = mask_fpe_numeric(original)
    assert masked is not None
    assert len(masked) == len(original)
    assert masked != original
    assert masked.count("-") == 3


def test_all_builtin_transforms_registered():
    assert "mask_hash" in BUILT_IN_TRANSFORMS
    assert "mask_nullify" in BUILT_IN_TRANSFORMS
    assert "bit_to_bool" in BUILT_IN_TRANSFORMS
