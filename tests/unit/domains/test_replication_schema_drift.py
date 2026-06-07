"""
Module: test_replication_schema_drift.py
Purpose: TDD tests for replication schema drift detection
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from domains.replication.schema_drift_detector import (
    TableSchemaSnapshot,
    detect_schema_drift,
)


def _snap(
    name: str,
    columns: list[str],
    *,
    schema: str = "dbo",
    pk: list[str] | None = None,
) -> TableSchemaSnapshot:
    return TableSchemaSnapshot(
        schema_name=schema,
        table_name=name,
        columns=columns,
        pk_columns=pk or (["id"] if "id" in columns else []),
    )


class TestSchemaDriftDetector:
    def test_no_target_table_is_blocker(self):
        concerns = detect_schema_drift(_snap("orders", ["id", "status"]), None)
        assert any(c.level == "blocker" and "missing" in c.message.lower() for c in concerns)

    def test_missing_columns_are_warnings(self):
        src = _snap("orders", ["id", "status", "updated_at"])
        tgt = _snap("orders", ["id", "status"], schema="public")
        concerns = detect_schema_drift(src, tgt)
        assert any(c.level == "warning" and "updated_at" in c.message for c in concerns)

    def test_extra_target_columns_are_info(self):
        src = _snap("orders", ["id"])
        tgt = _snap("orders", ["id", "legacy_col"], schema="public")
        concerns = detect_schema_drift(src, tgt)
        assert any(c.level == "info" and "legacy_col" in c.message for c in concerns)

    def test_exact_match_has_no_significant_concerns(self):
        cols = ["id", "status"]
        concerns = detect_schema_drift(
            _snap("orders", cols),
            _snap("orders", cols, schema="public"),
        )
        assert not any(c.level in ("warning", "blocker") for c in concerns)

    def test_pk_mismatch_is_warning(self):
        src = _snap("orders", ["id", "status"], pk=["id"])
        tgt = _snap("orders", ["id", "status"], schema="public", pk=["status"])
        concerns = detect_schema_drift(src, tgt)
        assert any(c.level == "warning" and "primary key" in c.message.lower() for c in concerns)
