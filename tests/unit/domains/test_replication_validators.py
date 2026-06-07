"""
Module: test_replication_validators.py
Purpose: TDD tests for replication identifier validation (security)
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import pytest

from domains.replication.validators import validate_identifier, validate_table_list


class TestReplicationValidators:
    def test_valid_identifiers(self):
        assert validate_identifier("dbo") == "dbo"
        assert validate_identifier("Orders_2024") == "Orders_2024"

    def test_rejects_sql_injection(self):
        with pytest.raises(ValueError, match="invalid"):
            validate_identifier("dbo; DROP TABLE users")

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            validate_identifier("")

    def test_validate_table_list_dedupes(self):
        assert validate_table_list(["A", "a", "B"]) == ["A", "B"]

    def test_validate_table_list_rejects_invalid(self):
        with pytest.raises(ValueError):
            validate_table_list(["good", "bad-name"])
