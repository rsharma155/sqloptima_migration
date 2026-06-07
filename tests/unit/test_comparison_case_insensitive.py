"""
Module: test_comparison_case_insensitive.py
Purpose: Tests that ComparisonEngine is case-insensitive when matching source and target objects
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import pytest

from domains.comparison.comparison_engine import ComparisonEngine, MatchStatus
from shared.kernel.database_object import (
    Column,
    DataType,
    DatabaseObject,
    DatabaseObjectType,
    Table,
)


def _make_table(name: str, schema: str = "dbo", db: str = "TestDB") -> Table:
    col = Column(
        column_name="id",
        ordinal_position=1,
        data_type=DataType(type_name="int"),
        is_nullable=False,
    )
    return Table(
        database_name=db,
        schema_name=schema,
        object_name=name,
        columns=[col],
    )


def _make_proc(name: str, schema: str = "dbo", db: str = "TestDB") -> DatabaseObject:
    return DatabaseObject(
        object_type=DatabaseObjectType.PROCEDURE,
        database_name=db,
        schema_name=schema,
        object_name=name,
    )


def _make_func(name: str, schema: str = "dbo", db: str = "TestDB") -> DatabaseObject:
    return DatabaseObject(
        object_type=DatabaseObjectType.FUNCTION,
        database_name=db,
        schema_name=schema,
        object_name=name,
    )


class TestTableCaseInsensitiveMatching:
    """SQL Server preserves case; PostgreSQL folds to lowercase.
    ComparisonEngine must normalize before matching.
    """

    def test_mixed_case_tables_are_matched_not_source_only(self):
        """UserProfile (SQL Server) must match userprofile (PostgreSQL)."""
        engine = ComparisonEngine()
        src = {"TestDB.dbo": [_make_table("UserProfile")]}
        tgt = {"TestDB.dbo": [_make_table("userprofile")]}

        matches = engine.compare_tables(src, tgt)

        statuses = {m.match_status for m in matches}
        assert MatchStatus.SOURCE_ONLY not in statuses, (
            "UserProfile and userprofile should not be SOURCE_ONLY"
        )
        assert MatchStatus.TARGET_ONLY not in statuses, (
            "userprofile should not be TARGET_ONLY"
        )

    def test_mixed_case_tables_produce_exact_or_partial_match(self):
        """A case-only-different pair must produce EXACT or PARTIAL, not ONLY."""
        engine = ComparisonEngine()
        src = {"TestDB.dbo": [_make_table("OrderDetail")]}
        tgt = {"TestDB.dbo": [_make_table("orderdetail")]}

        matches = engine.compare_tables(src, tgt)

        assert len(matches) == 1
        assert matches[0].match_status in (MatchStatus.EXACT, MatchStatus.PARTIAL)

    def test_fully_uppercase_source_matches_lowercase_target(self):
        """CUSTOMERS (SQL Server) matches customers (PostgreSQL)."""
        engine = ComparisonEngine()
        src = {"db.dbo": [_make_table("CUSTOMERS")]}
        tgt = {"db.dbo": [_make_table("customers")]}

        matches = engine.compare_tables(src, tgt)

        assert len(matches) == 1
        assert matches[0].match_status in (MatchStatus.EXACT, MatchStatus.PARTIAL)

    def test_truly_different_tables_still_reported_as_source_and_target_only(self):
        """Tables with genuinely different names must still be detected as missing."""
        engine = ComparisonEngine()
        src = {"db.dbo": [_make_table("Orders")]}
        tgt = {"db.dbo": [_make_table("Customers")]}

        matches = engine.compare_tables(src, tgt)
        statuses = [m.match_status for m in matches]

        assert MatchStatus.SOURCE_ONLY in statuses
        assert MatchStatus.TARGET_ONLY in statuses

    def test_multiple_tables_some_case_different_some_missing(self):
        """Mixed scenario: some match case-insensitively, one truly missing."""
        engine = ComparisonEngine()
        src = {"db.dbo": [
            _make_table("UserProfile"),
            _make_table("Orders"),
        ]}
        tgt = {"db.dbo": [
            _make_table("userprofile"),
            # Orders missing on target
        ]}

        matches = engine.compare_tables(src, tgt)
        statuses = [m.match_status for m in matches]

        assert MatchStatus.SOURCE_ONLY in statuses, "Orders should be SOURCE_ONLY"
        # UserProfile/userprofile pair must NOT be SOURCE_ONLY or TARGET_ONLY
        source_only_matches = [
            m for m in matches if m.match_status == MatchStatus.SOURCE_ONLY
        ]
        for m in source_only_matches:
            name = m.source_object.object_name if m.source_object else ""
            assert name.lower() != "userprofile", (
                "UserProfile should not be SOURCE_ONLY — it matches userprofile"
            )


class TestProcedureCaseInsensitiveMatching:
    """Procedures should also be matched case-insensitively."""

    def test_procedure_mixed_case_matched(self):
        engine = ComparisonEngine()
        src = {"db.dbo": [_make_proc("usp_GetUser")]}
        tgt = {"db.dbo": [_make_proc("usp_getuser")]}

        matches = engine.compare_procedures(src, tgt)
        statuses = {m.match_status for m in matches}

        assert MatchStatus.SOURCE_ONLY not in statuses
        assert MatchStatus.TARGET_ONLY not in statuses

    def test_procedure_truly_different_still_detected(self):
        engine = ComparisonEngine()
        src = {"db.dbo": [_make_proc("usp_GetUser")]}
        tgt = {"db.dbo": [_make_proc("usp_GetOrder")]}

        matches = engine.compare_procedures(src, tgt)
        statuses = [m.match_status for m in matches]

        assert MatchStatus.SOURCE_ONLY in statuses
        assert MatchStatus.TARGET_ONLY in statuses


class TestFunctionCaseInsensitiveMatching:
    """Functions should also be matched case-insensitively."""

    def test_function_mixed_case_matched(self):
        engine = ComparisonEngine()
        src = {"db.dbo": [_make_func("fn_CalcAge")]}
        tgt = {"db.dbo": [_make_func("fn_calcage")]}

        matches = engine.compare_functions(src, tgt)
        statuses = {m.match_status for m in matches}

        assert MatchStatus.SOURCE_ONLY not in statuses
        assert MatchStatus.TARGET_ONLY not in statuses
