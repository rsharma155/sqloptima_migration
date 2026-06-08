"""Unit tests for target table preflight and policy validation."""

from __future__ import annotations

import pytest

from application.go_engine_migration.target_table_preflight import (
    TargetTablePolicy,
    TargetTablePreflightError,
    validate_table_policies,
    _suggest_policy,
)


class TestSuggestPolicy:
    def test_missing_table_no_policy(self):
        assert _suggest_policy(False, 0) is None

    def test_empty_existing_table(self):
        assert _suggest_policy(True, 0) == TargetTablePolicy.DROP_EMPTY_RECREATE

    def test_populated_existing_table(self):
        assert _suggest_policy(True, 100) == TargetTablePolicy.USE_EXISTING


class TestValidateTablePolicies:
    def test_no_conflicts_without_policies(self):
        validate_table_policies(
            [{"table_name": "orders", "requires_action": False, "row_count": 0}],
            None,
        )

    def test_missing_policy_raises(self):
        with pytest.raises(TargetTablePreflightError, match="choose a policy"):
            validate_table_policies(
                [{"table_name": "orders", "requires_action": True, "row_count": 10}],
                {},
            )

    def test_drop_empty_on_populated_table_raises(self):
        with pytest.raises(TargetTablePreflightError, match="truncate_reload"):
            validate_table_policies(
                [{"table_name": "orders", "requires_action": True, "row_count": 5}],
                {"orders": TargetTablePolicy.DROP_EMPTY_RECREATE.value},
            )

    def test_truncate_policy_accepted(self):
        validate_table_policies(
            [{"table_name": "orders", "requires_action": True, "row_count": 5}],
            {"orders": TargetTablePolicy.TRUNCATE_RELOAD.value},
        )
