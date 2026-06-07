"""
Module: test_comparison_engine.py
Purpose: Unit tests
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from uuid import UUID

from domains.comparison.comparison_engine import (
    ComparisonEngine,
    MatchStatus,
    ObjectMatch,
)
from domains.comparison.object_comparator import DiffEntry, ObjectComparator
from domains.discovery.discovery_engine import DiscoveryResult
from shared.kernel.database_object import (
    Column,
    DatabaseObject,
    DatabaseObjectType,
    DataType,
    Table,
)


def _make_column(
    name: str, type_name: str, nullable: bool = True, default: str | None = None,
) -> Column:
    return Column(
        table_id=UUID(int=0),
        column_name=name,
        ordinal_position=0,
        data_type=DataType(type_name=type_name, is_nullable=nullable),
        is_nullable=nullable,
        default_value=default,
    )


def _make_table(
    name: str, columns: list[Column], schema: str = "dbo", db: str = "test_db",
) -> Table:
    return Table(
        database_name=db,
        schema_name=schema,
        object_name=name,
        columns=columns,
    )


def _make_discovery_result(
    tables: dict[str, list[Table]] | None = None,
    procedures: dict[str, list[DatabaseObject]] | None = None,
    functions: dict[str, list[DatabaseObject]] | None = None,
    db_name: str = "test_db",
) -> DiscoveryResult:
    result = DiscoveryResult()
    result.databases = [
        DatabaseObject(
            object_type=DatabaseObjectType.DATABASE,
            database_name=db_name,
            schema_name="",
            object_name=db_name,
        )
    ]
    if tables:
        result.tables.update(tables)
        for tbl_list in tables.values():
            result.all_objects.extend(tbl_list)
    if procedures:
        result.procedures.update(procedures)
        for proc_list in procedures.values():
            result.all_objects.extend(proc_list)
    if functions:
        result.functions.update(functions)
        for func_list in functions.values():
            result.all_objects.extend(func_list)
    return result


class TestObjectComparator:

    def test_compare_identical_types(self):
        comparator = ObjectComparator()
        src = DataType(type_name="INT")
        tgt = DataType(type_name="INTEGER")
        diff = comparator.compare_column_types(src, tgt)
        assert diff is None

    def test_compare_mismatched_types(self):
        comparator = ObjectComparator()
        src = DataType(type_name="INT")
        tgt = DataType(type_name="TEXT")
        diff = comparator.compare_column_types(src, tgt)
        assert diff is not None
        assert diff.severity == "warning"

    def test_compare_identical_columns(self):
        comparator = ObjectComparator()
        cols_a = [_make_column("id", "INT"), _make_column("name", "VARCHAR")]
        cols_b = [_make_column("id", "INTEGER"), _make_column("name", "VARCHAR")]
        diffs = comparator.compare_columns(cols_a, cols_b)
        assert len(diffs) == 0

    def test_compare_missing_column(self):
        comparator = ObjectComparator()
        cols_a = [_make_column("id", "INT"), _make_column("name", "VARCHAR")]
        cols_b = [_make_column("id", "INTEGER")]
        diffs = comparator.compare_columns(cols_a, cols_b)
        assert len(diffs) == 1
        assert diffs[0].severity == "error"

    def test_compare_nullability_diff(self):
        comparator = ObjectComparator()
        cols_a = [_make_column("id", "INT", nullable=False)]
        cols_b = [_make_column("id", "INTEGER", nullable=True)]
        diffs = comparator.compare_columns(cols_a, cols_b)
        assert len(diffs) == 1
        assert "nullable" in diffs[0].property_name


class TestComparisonEngine:

    def test_compare_identical_tables(self):
        engine = ComparisonEngine()
        cols = [_make_column("id", "INT"), _make_column("name", "VARCHAR")]
        src_table = _make_table("users", cols)
        tgt_table = _make_table(
            "users",
            [_make_column("id", "INTEGER"), _make_column("name", "VARCHAR")],
        )

        source_result = _make_discovery_result(tables={"test_db.dbo": [src_table]})
        target_result = _make_discovery_result(tables={"test_db.dbo": [tgt_table]})

        result = engine.compare_databases(source_result, target_result)

        assert result.matched == 1
        assert result.source_only == 0
        assert result.target_only == 0
        assert result.partial_match == 0
        assert result.total_source_objects == 1
        assert result.total_target_objects == 1

    def test_compare_tables_with_diff_columns(self):
        engine = ComparisonEngine()
        src_cols = [_make_column("id", "INT"), _make_column("name", "VARCHAR")]
        tgt_cols = [
            _make_column("id", "INTEGER"),
            _make_column("name", "VARCHAR"),
            _make_column("email", "VARCHAR"),
        ]

        src_table = _make_table("users", src_cols)
        tgt_table = _make_table("users", tgt_cols)

        source_result = _make_discovery_result(tables={"test_db.dbo": [src_table]})
        target_result = _make_discovery_result(tables={"test_db.dbo": [tgt_table]})

        result = engine.compare_databases(source_result, target_result)

        assert result.partial_match == 1
        assert result.matched == 0

    def test_compare_source_only_table(self):
        engine = ComparisonEngine()
        src_table = _make_table("users", [_make_column("id", "INT")])

        source_result = _make_discovery_result(tables={"test_db.dbo": [src_table]})
        target_result = _make_discovery_result(tables={})

        result = engine.compare_databases(source_result, target_result)

        assert result.source_only == 1
        assert result.matched == 0
        assert result.target_only == 0

    def test_compare_column_type_mapping(self):
        comparator = ObjectComparator()
        src_type = DataType(type_name="NVARCHAR")
        tgt_type = DataType(type_name="VARCHAR")
        diff = comparator.compare_column_types(src_type, tgt_type)
        assert diff is None

        src_type = DataType(type_name="NVARCHAR")
        tgt_type = DataType(type_name="TEXT")
        diff = comparator.compare_column_types(src_type, tgt_type)
        assert diff is not None

    def test_compare_procedures(self):
        engine = ComparisonEngine()
        key = "test_db.dbo"

        src_proc = DatabaseObject(
            object_type=DatabaseObjectType.PROCEDURE,
            database_name="test_db",
            schema_name="dbo",
            object_name="usp_get_user",
            source_definition=(
                "CREATE PROC usp_get_user @id INT"
                " AS SELECT * FROM users WHERE id = @id"
            ),
        )
        tgt_proc = DatabaseObject(
            object_type=DatabaseObjectType.PROCEDURE,
            database_name="test_db",
            schema_name="dbo",
            object_name="usp_get_user",
            source_definition=(
                "CREATE OR REPLACE PROCEDURE usp_get_user(p_id INT)"
                " AS $$ SELECT * FROM users WHERE id = p_id; $$ LANGUAGE sql"
            ),
        )

        source_result = _make_discovery_result(procedures={key: [src_proc]})
        target_result = _make_discovery_result(procedures={key: [tgt_proc]})

        result = engine.compare_databases(source_result, target_result)

        assert result.matched == 0
        assert result.partial_match == 1

    def test_build_comparison_tree(self):
        engine = ComparisonEngine()
        cols = [_make_column("id", "INT")]
        src_table = _make_table("users", cols)
        tgt_table = _make_table("users", [_make_column("id", "INTEGER")])

        key = "test_db.dbo"
        source_result = _make_discovery_result(tables={key: [src_table]})
        target_result = _make_discovery_result(tables={key: [tgt_table]})

        result = engine.compare_databases(source_result, target_result)

        assert len(result.tree) == 1
        db_node = result.tree[0]
        assert db_node.node_type == "database"
        assert db_node.name == "test_db"
        assert len(db_node.children) == 1

        schema_node = db_node.children[0]
        assert schema_node.node_type == "schema"
        assert schema_node.name == "dbo"
        assert len(schema_node.children) == 1

        table_node = schema_node.children[0]
        assert table_node.node_type == "table"
        assert table_node.name == "users"
        assert table_node.status == MatchStatus.EXACT

    def test_compare_databases_full(self):
        engine = ComparisonEngine()
        key = "test_db.dbo"

        src_tables = [
            _make_table("users", [_make_column("id", "INT"), _make_column("name", "VARCHAR")]),
            _make_table("orders", [_make_column("id", "INT")]),
        ]
        tgt_tables = [
            _make_table("users", [_make_column("id", "INTEGER"), _make_column("name", "VARCHAR")]),
            _make_table("products", [_make_column("id", "INTEGER")]),
        ]

        src_proc = DatabaseObject(
            object_type=DatabaseObjectType.PROCEDURE,
            database_name="test_db",
            schema_name="dbo",
            object_name="usp_get_user",
        )
        tgt_proc = DatabaseObject(
            object_type=DatabaseObjectType.PROCEDURE,
            database_name="test_db",
            schema_name="dbo",
            object_name="usp_get_user",
        )

        source_result = _make_discovery_result(
            tables={key: src_tables},
            procedures={key: [src_proc]},
        )
        target_result = _make_discovery_result(
            tables={key: tgt_tables},
            procedures={key: [tgt_proc]},
        )

        result = engine.compare_databases(source_result, target_result)

        assert result.matched >= 1
        assert result.source_only >= 1
        assert result.target_only >= 1
        assert result.total_source_objects > 0
        assert result.total_target_objects > 0
        assert result.duration_ms >= 0

    def test_target_only_table(self):
        engine = ComparisonEngine()
        tgt_table = _make_table("products", [_make_column("id", "INTEGER")])

        source_result = _make_discovery_result(tables={})
        target_result = _make_discovery_result(tables={"test_db.dbo": [tgt_table]})

        result = engine.compare_databases(source_result, target_result)

        assert result.target_only == 1
        assert result.source_only == 0
        assert result.matched == 0

    def test_compare_dbo_to_public_cross_schema(self):
        """SQL Server dbo tables must match PostgreSQL public tables by name."""
        engine = ComparisonEngine()
        cols = [_make_column("id", "INT"), _make_column("name", "VARCHAR")]
        src_table = _make_table("orders", cols, schema="dbo", db="AdventureWorks")
        tgt_table = _make_table(
            "orders",
            [_make_column("id", "INTEGER"), _make_column("name", "VARCHAR")],
            schema="public",
            db="migration_db",
        )

        source_result = _make_discovery_result(
            tables={"AdventureWorks.dbo": [src_table]},
            db_name="AdventureWorks",
        )
        target_result = _make_discovery_result(
            tables={"migration_db.public": [tgt_table]},
            db_name="migration_db",
        )

        result = engine.compare_databases(
            source_result,
            target_result,
            source_schema="dbo",
            target_schema="public",
        )

        assert result.matched == 1
        assert result.source_only == 0
        assert result.target_only == 0
        assert result.tree[0].properties["target_database"] == "migration_db"
        schema_node = result.tree[0].children[0]
        assert schema_node.name == "dbo"
        assert schema_node.properties["target_schema"] == "public"

    def test_object_match_dataclass(self):
        src = _make_table("users", [])
        match = ObjectMatch(
            source_object=src,
            target_object=None,
            match_status=MatchStatus.SOURCE_ONLY,
            differences=[DiffEntry("col", "a", "b", "warning")],
        )
        assert match.match_status == MatchStatus.SOURCE_ONLY
        assert match.source_object is not None
        assert match.target_object is None
        assert len(match.differences) == 1
