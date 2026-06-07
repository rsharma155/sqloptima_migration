"""Unit tests for user-approved column type overrides."""

from __future__ import annotations

import pytest

from domains.assessment.assessment_engine import (
    AssessmentEngine,
    DatabaseAssessment,
    MigrationTier,
    TableAssessment,
)
from domains.migration.column_type_override import (
    ResolvedColumnTypeOverride,
    catalog_for_api,
    is_unsupported_type_only_blocker,
    lookup_option,
    missing_type_override_keys,
    override_key,
    resolve_overrides_for_tables,
    table_blocked_after_overrides,
)
from shared.kernel.database_object import Column, DataType, Table
from application.migration_readiness_service import assert_tables_ready_for_migration


def _misc_types_table() -> Table:
    return Table(
        database_name="AppDb",
        schema_name="dbo",
        object_name="dt_MiscTypes",
        columns=[
            Column(
                table_id=None,  # type: ignore[arg-type]
                column_name="id",
                ordinal_position=1,
                data_type=DataType(type_name="int", is_nullable=False),
                is_nullable=False,
                is_identity=True,
            ),
            Column(
                table_id=None,  # type: ignore[arg-type]
                column_name="col_sql_variant",
                ordinal_position=2,
                data_type=DataType(type_name="sql_variant"),
                is_nullable=True,
            ),
            Column(
                table_id=None,  # type: ignore[arg-type]
                column_name="col_hierarchyid",
                ordinal_position=3,
                data_type=DataType(type_name="hierarchyid"),
                is_nullable=True,
            ),
        ],
    )


def test_assessment_flags_unsupported_columns_with_override_hint():
    engine = AssessmentEngine()
    ta = engine.assess_table(_misc_types_table())
    assert ta.migration_tier == MigrationTier.BLOCKER
    assert "col_sql_variant" in ta.blocker_types
    assert "col_hierarchyid" in ta.blocker_types
    assert len(ta.unsupported_type_columns) == 2
    assert is_unsupported_type_only_blocker(ta)
    assert all("migration wizard" in b for b in ta.blockers)


def test_catalog_includes_all_blocker_source_types():
    catalog = catalog_for_api()
    for source_type in ("sql_variant", "hierarchyid", "geometry", "geography"):
        assert source_type in catalog
        assert len(catalog[source_type]) >= 2


def test_resolve_overrides_builds_cast_expressions():
    engine = AssessmentEngine()
    ta = engine.assess_table(_misc_types_table())
    assessment = DatabaseAssessment(database_name="AppDb", tables=[ta])
    overrides = {
        override_key("dt_MiscTypes", "col_sql_variant"): "sql_variant_text",
        override_key("dt_MiscTypes", "col_hierarchyid"): "hierarchyid_ltree",
    }
    resolved = resolve_overrides_for_tables(assessment, ["dt_MiscTypes"], overrides)
    sv = resolved[override_key("dt_MiscTypes", "col_sql_variant")]
    assert sv.pg_ddl_type == "text"
    assert "CAST([col_sql_variant] AS nvarchar(max))" == sv.source_cast_expression
    hi = resolved[override_key("dt_MiscTypes", "col_hierarchyid")]
    assert hi.pg_ddl_type == "ltree"
    assert hi.requires_extension == "ltree"
    assert "[col_hierarchyid].ToString()" == hi.source_cast_expression


def test_resolve_overrides_rejects_incomplete_selection():
    engine = AssessmentEngine()
    ta = engine.assess_table(_misc_types_table())
    assessment = DatabaseAssessment(database_name="AppDb", tables=[ta])
    with pytest.raises(ValueError, match="missing type overrides"):
        resolve_overrides_for_tables(
            assessment,
            ["dt_MiscTypes"],
            {override_key("dt_MiscTypes", "col_sql_variant"): "sql_variant_text"},
        )


def test_readiness_allows_migration_when_overrides_complete():
    engine = AssessmentEngine()
    ta = engine.assess_table(_misc_types_table())
    assessment = DatabaseAssessment(database_name="AppDb", tables=[ta])
    overrides = {
        override_key("dt_MiscTypes", "col_sql_variant"): "sql_variant_jsonb",
        override_key("dt_MiscTypes", "col_hierarchyid"): "hierarchyid_text",
    }
    still_blocked, _ = table_blocked_after_overrides(ta, overrides)
    assert still_blocked is False
    assert_tables_ready_for_migration(
        assessment,
        ["dt_MiscTypes"],
        column_type_overrides=overrides,
    )


def test_missing_type_override_keys():
    ta = TableAssessment(
        table_name="dt_MiscTypes",
        schema_name="dbo",
        migration_tier=MigrationTier.BLOCKER,
        blocker_types=["col_sql_variant", "col_hierarchyid"],
        blockers=["Column 'col_sql_variant' uses unsupported type 'sql_variant' — choose..."],
    )
    missing = missing_type_override_keys(ta, {})
    assert missing == [
        override_key("dt_MiscTypes", "col_sql_variant"),
        override_key("dt_MiscTypes", "col_hierarchyid"),
    ]


def test_jsonb_override_loads_as_text_for_copy():
    ro = ResolvedColumnTypeOverride(
        table_name="dt_MiscTypes",
        column_name="col_sql_variant",
        source_type="sql_variant",
        option_id="sql_variant_jsonb",
        pg_ddl_type="jsonb",
        extract_type="nvarchar",
        source_cast_expression="CAST([col_sql_variant] AS nvarchar(max))",
    )
    assert ro.load_pg_ddl_type == "text"
    assert ro.needs_finalize_type_cast is True
    assert ro.finalize_cast_using_sql() == '"col_sql_variant"::jsonb'


def test_source_select_expression_uses_override_cast():
    from domains.migration.column_type_override import source_select_expression

    ro = ResolvedColumnTypeOverride(
        table_name="dt_MiscTypes",
        column_name="col_sql_variant",
        source_type="sql_variant",
        option_id="sql_variant_text",
        pg_ddl_type="text",
        extract_type="nvarchar",
        source_cast_expression="CAST([col_sql_variant] AS nvarchar(max))",
    )
    expr = source_select_expression(
        "dt_MiscTypes",
        "col_sql_variant",
        "sql_variant",
        {ro.override_key: ro},
    )
    assert expr == "CAST([col_sql_variant] AS nvarchar(max)) AS [col_sql_variant]"


def test_lookup_option_returns_none_for_unknown():
    assert lookup_option("sql_variant", "not_a_real_option") is None
