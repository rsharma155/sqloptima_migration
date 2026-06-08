"""
Module: test_index_constraint_comparison.py
Purpose: Tests for index and constraint comparison between source and target schemas
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import pytest

from domains.comparison.index_comparator import IndexComparator
from domains.comparison.constraint_comparator import ConstraintComparator
from domains.comparison.comparison_engine import ComparisonEngine, MatchStatus
from domains.comparison.object_comparator import DiffEntry
from shared.kernel.database_object import (
    Column,
    DataType,
    DatabaseObject,
    DatabaseObjectType,
    Table,
)


def _make_index(name: str, schema: str = "dbo", db: str = "TestDB", **props) -> DatabaseObject:
    return DatabaseObject(
        object_type=DatabaseObjectType.INDEX,
        database_name=db,
        schema_name=schema,
        object_name=name,
        properties=props or {"is_unique": False, "columns": "id"},
    )


def _make_constraint(name: str, schema: str = "dbo", db: str = "TestDB", **props) -> DatabaseObject:
    return DatabaseObject(
        object_type=DatabaseObjectType.CONSTRAINT,
        database_name=db,
        schema_name=schema,
        object_name=name,
        properties=props or {"constraint_type": "CHECK"},
    )


def _make_table_with_indexes(
    name: str,
    indexes: list[DatabaseObject] | None = None,
    constraints: list[DatabaseObject] | None = None,
) -> Table:
    col = Column(
        column_name="id",
        ordinal_position=1,
        data_type=DataType(type_name="int"),
        is_nullable=False,
    )
    t = Table(
        database_name="TestDB",
        schema_name="dbo",
        object_name=name,
        columns=[col],
    )
    t.properties["indexes"] = indexes or []
    t.properties["constraints"] = constraints or []
    return t


class TestIndexComparator:

    def test_missing_index_on_target_is_reported(self):
        comparator = IndexComparator()
        src = [_make_index("IX_Users_Email")]
        tgt = []

        diffs = comparator.compare(src, tgt)

        assert len(diffs) == 1
        assert "IX_Users_Email" in diffs[0].property_name
        assert diffs[0].source_value == "exists"
        assert diffs[0].target_value == "<missing>"
        assert diffs[0].severity == "error"

    def test_extra_index_on_target_is_reported(self):
        comparator = IndexComparator()
        src = []
        tgt = [_make_index("IX_Users_Email")]

        diffs = comparator.compare(src, tgt)

        assert len(diffs) == 1
        assert "IX_Users_Email" in diffs[0].property_name
        assert diffs[0].source_value == "<missing>"
        assert diffs[0].target_value == "exists"

    def test_matching_indexes_produce_no_diff(self):
        comparator = IndexComparator()
        src = [_make_index("IX_Users_Email"), _make_index("IX_Users_Name")]
        tgt = [_make_index("IX_Users_Email"), _make_index("IX_Users_Name")]

        diffs = comparator.compare(src, tgt)

        assert diffs == []

    def test_index_comparison_case_insensitive(self):
        """Index names may differ in case between SQL Server and PostgreSQL."""
        comparator = IndexComparator()
        src = [_make_index("IX_Users_Email")]
        tgt = [_make_index("ix_users_email")]

        diffs = comparator.compare(src, tgt)

        assert diffs == [], "Index names differing only in case must match"

    def test_multiple_indexes_partial_match(self):
        comparator = IndexComparator()
        src = [_make_index("IX_A"), _make_index("IX_B"), _make_index("IX_C")]
        tgt = [_make_index("IX_A"), _make_index("ix_b")]  # IX_C missing

        diffs = comparator.compare(src, tgt)

        diff_names = [d.property_name for d in diffs]
        assert any("IX_C" in n or "ix_c" in n for n in diff_names), (
            "IX_C should be reported as missing"
        )
        # IX_A and IX_B should match
        assert not any("IX_A" in n for n in diff_names)
        assert not any("IX_B" in n or "ix_b" in n for n in diff_names)

    def test_empty_both_sides_produces_no_diff(self):
        comparator = IndexComparator()
        diffs = comparator.compare([], [])
        assert diffs == []


class TestConstraintComparator:

    def test_missing_constraint_on_target_is_reported(self):
        comparator = ConstraintComparator()
        src = [_make_constraint("UQ_Users_Email")]
        tgt = []

        diffs = comparator.compare(src, tgt)

        assert len(diffs) == 1
        assert "UQ_Users_Email" in diffs[0].property_name
        assert diffs[0].source_value == "exists"
        assert diffs[0].target_value == "<missing>"
        assert diffs[0].severity == "error"

    def test_extra_constraint_on_target_is_reported(self):
        comparator = ConstraintComparator()
        src = []
        tgt = [_make_constraint("CHK_Age_Positive")]

        diffs = comparator.compare(src, tgt)

        assert len(diffs) == 1
        assert diffs[0].source_value == "<missing>"

    def test_matching_constraints_produce_no_diff(self):
        comparator = ConstraintComparator()
        src = [_make_constraint("UQ_Email"), _make_constraint("CHK_Age")]
        tgt = [_make_constraint("UQ_Email"), _make_constraint("CHK_Age")]

        diffs = comparator.compare(src, tgt)

        assert diffs == []

    def test_constraint_comparison_case_insensitive(self):
        comparator = ConstraintComparator()
        src = [_make_constraint("UQ_Users_Email")]
        tgt = [_make_constraint("uq_users_email")]

        diffs = comparator.compare(src, tgt)

        assert diffs == [], "Constraint names differing only in case must match"

    def test_empty_both_sides_produces_no_diff(self):
        comparator = ConstraintComparator()
        diffs = comparator.compare([], [])
        assert diffs == []


class TestComparisonEngineWithIndexesAndConstraints:
    """ComparisonEngine._compare_table_columns must also compare indexes and constraints."""

    def _make_table_with_idx_constraint(
        self,
        name: str,
        indexes: list[DatabaseObject] | None = None,
        constraints: list[DatabaseObject] | None = None,
    ) -> Table:
        col = Column(
            column_name="id",
            ordinal_position=1,
            data_type=DataType(type_name="INT"),
            is_nullable=False,
        )
        t = Table(
            database_name="TestDB",
            schema_name="dbo",
            object_name=name,
            columns=[col],
        )
        t.properties["indexes"] = indexes or []
        t.properties["constraints"] = constraints or []
        return t

    def _make_pg_table_with_idx_constraint(
        self,
        name: str,
        indexes: list[DatabaseObject] | None = None,
        constraints: list[DatabaseObject] | None = None,
    ) -> Table:
        col = Column(
            column_name="id",
            ordinal_position=1,
            data_type=DataType(type_name="INTEGER"),
            is_nullable=False,
        )
        t = Table(
            database_name="TestDB",
            schema_name="dbo",
            object_name=name,
            columns=[col],
        )
        t.properties["indexes"] = indexes or []
        t.properties["constraints"] = constraints or []
        return t

    def test_missing_index_detected_through_comparison_engine(self):
        from domains.comparison.index_comparator import IndexComparator
        from domains.comparison.constraint_comparator import ConstraintComparator

        idx = _make_index("IX_Email")
        engine = ComparisonEngine(
            index_comparator=IndexComparator(),
            constraint_comparator=ConstraintComparator(),
        )

        src = self._make_table_with_idx_constraint("Users", indexes=[idx])
        tgt = self._make_table_with_idx_constraint("users", indexes=[])

        src_dict = {"TestDB.dbo": [src]}
        tgt_dict = {"TestDB.dbo": [tgt]}

        matches = engine.compare_tables(src_dict, tgt_dict)

        assert len(matches) == 1
        match = matches[0]
        assert match.match_status == MatchStatus.PARTIAL
        diff_names = [d.property_name for d in match.differences]
        assert any("IX_Email" in n for n in diff_names), (
            f"Expected IX_Email diff, got: {diff_names}"
        )

    def test_missing_constraint_detected_through_comparison_engine(self):
        from domains.comparison.index_comparator import IndexComparator
        from domains.comparison.constraint_comparator import ConstraintComparator

        cst = _make_constraint("UQ_Email")
        engine = ComparisonEngine(
            index_comparator=IndexComparator(),
            constraint_comparator=ConstraintComparator(),
        )

        src = self._make_table_with_idx_constraint("Users", constraints=[cst])
        tgt = self._make_table_with_idx_constraint("users", constraints=[])

        matches = engine.compare_tables(
            {"TestDB.dbo": [src]},
            {"TestDB.dbo": [tgt]},
        )

        assert len(matches) == 1
        match = matches[0]
        assert match.match_status == MatchStatus.PARTIAL
        diff_names = [d.property_name for d in match.differences]
        assert any("UQ_Email" in n for n in diff_names)

    def test_exact_match_when_indexes_and_constraints_match(self):
        from domains.comparison.index_comparator import IndexComparator
        from domains.comparison.constraint_comparator import ConstraintComparator

        idx = _make_index("IX_Email")
        cst = _make_constraint("UQ_Email")
        engine = ComparisonEngine(
            index_comparator=IndexComparator(),
            constraint_comparator=ConstraintComparator(),
        )

        src = self._make_table_with_idx_constraint("Users", indexes=[idx], constraints=[cst])
        tgt = self._make_pg_table_with_idx_constraint(
            "users",
            indexes=[_make_index("IX_Email")],
            constraints=[_make_constraint("UQ_Email")],
        )

        matches = engine.compare_tables(
            {"TestDB.dbo": [src]},
            {"TestDB.dbo": [tgt]},
        )

        assert len(matches) == 1
        assert matches[0].match_status == MatchStatus.EXACT
