"""
Module: test_replication_cdc_requirements.py
Purpose: TDD tests for CDC prerequisite validation
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from domains.replication.cdc_requirements import CdcStatus, validate_cdc_for_tables


class TestCdcRequirements:
    def test_db_disabled_returns_error(self):
        msg = validate_cdc_for_tables(CdcStatus(db_enabled=False, tables={}), ["Orders"])
        assert msg is not None
        assert "sp_cdc_enable_db" in msg

    def test_table_not_tracked_returns_error(self):
        status = CdcStatus(db_enabled=True, tables={"Orders": False, "Customers": True})
        msg = validate_cdc_for_tables(status, ["Orders"])
        assert msg is not None
        assert "Orders" in msg
        assert "sp_cdc_enable_table" in msg

    def test_all_tables_tracked_returns_none(self):
        status = CdcStatus(db_enabled=True, tables={"orders": True})
        assert validate_cdc_for_tables(status, ["Orders"]) is None

    def test_db_only_check_with_no_tables(self):
        assert validate_cdc_for_tables(CdcStatus(db_enabled=True, tables={}), []) is None
        assert validate_cdc_for_tables(CdcStatus(db_enabled=False, tables={}), []) is not None
