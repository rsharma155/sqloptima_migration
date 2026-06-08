"""Unit tests for procedural migration models and helpers."""

from __future__ import annotations

from application.conversion_factory import build_schema_mapping
from application.procedural_migration_service import (
    _convert_definition,
    _conversion_ready,
    _rewrite_routine_schema_qualifiers,
    _summarize_procedural_failures,
    build_initial_procedural_state,
)
from domains.migration.procedural_migration_models import (
    ProceduralMigrateStatus,
    ProceduralMigrationPhaseStatus,
    ProceduralMigrationState,
    ProceduralObjectKind,
    ProceduralObjectResult,
    ProceduralObjectSelection,
)
from domains.migration.source_throttle import SourceThrottleConfig


def test_build_schema_mapping_dbo_to_public():
    assert build_schema_mapping("dbo", None) == {"dbo": "public"}
    assert build_schema_mapping("dbo", "public") == {"dbo": "public"}


def test_build_schema_mapping_preserves_named_schema():
    assert build_schema_mapping("Sales", None) == {}
    assert build_schema_mapping("Sales", "Sales") == {}


def test_build_initial_procedural_state_empty():
    assert build_initial_procedural_state(
        source_schema="dbo",
        target_schema=None,
        procedures=None,
        functions=None,
    ) is None


def test_build_initial_procedural_state_with_selection():
    state = build_initial_procedural_state(
        source_schema="dbo",
        target_schema="public",
        procedures=["usp_a"],
        functions=["ufn_b"],
    )
    assert state is not None
    assert state.selected_procedures == ["usp_a"]
    assert state.selected_functions == ["ufn_b"]
    assert state.status == ProceduralMigrationPhaseStatus.PENDING
    assert state.has_selection()


def test_procedural_object_selection_from_name():
    proc = ProceduralObjectSelection.from_name("usp_x", "procedure")
    func = ProceduralObjectSelection.from_name("ufn_y", "scalar_function")
    assert proc.object_type.value == "procedure"
    assert func.object_type.value == "function"


def test_procedural_migration_state_roundtrip():
    state = ProceduralMigrationState(
        source_schema="dbo",
        target_schema="public",
        selected_procedures=["usp_a"],
        status=ProceduralMigrationPhaseStatus.PENDING,
    )
    restored = ProceduralMigrationState.from_dict(state.to_dict())
    assert restored.selected_procedures == ["usp_a"]
    assert restored.target_schema == "public"


def test_rewrite_routine_schema_qualifiers_dbo_to_public():
    sql = "CREATE OR REPLACE PROCEDURE dbo.usp_x()\nLANGUAGE plpgsql\nAS $$\nSELECT * FROM dbo.Customers;\n$$;"
    out = _rewrite_routine_schema_qualifiers(sql, "dbo", "public")
    assert "dbo." not in out.lower()
    assert "public.usp_x" in out
    assert "public.Customers" in out


def test_summarize_procedural_failures_includes_errors():
    state = ProceduralMigrationState(
        objects={
            "dbo.usp_a": ProceduralObjectResult(
                name="usp_a",
                schema_name="dbo",
                object_type=ProceduralObjectKind.PROCEDURE,
                status=ProceduralMigrateStatus.FAILED,
                errors=["syntax error at FOR"],
            )
        }
    )
    summary = _summarize_procedural_failures(state)
    assert summary is not None
    assert "usp_a" in summary
    assert "syntax error" in summary


def test_source_throttle_defaults():
    cfg = SourceThrottleConfig()
    assert cfg.small_table_delay_sec == 1.0
    assert cfg.large_table_delay_sec == 4.0
    assert cfg.large_table_row_threshold == 100_000


_CURSOR_SP = """
CREATE PROCEDURE dbo.usp_BuildCustomerList_Bad
AS
BEGIN
    DECLARE @CustomerList NVARCHAR(MAX) = '';
    DECLARE @CustomerName NVARCHAR(200);
    DECLARE name_cursor CURSOR FOR
    SELECT TOP 10000 FirstName + ' ' + LastName FROM Customers WHERE CustomerStatus = 'VIP';
    OPEN name_cursor;
    FETCH NEXT FROM name_cursor INTO @CustomerName;
    WHILE @@FETCH_STATUS = 0
    BEGIN
        SET @CustomerList = @CustomerList + @CustomerName + ', ';
        FETCH NEXT FROM name_cursor INTO @CustomerName;
    END
    CLOSE name_cursor;
    SELECT @CustomerList as CustomerList;
END
"""


def test_convert_definition_cursor_sp_is_deployable():
    obj = _convert_definition(
        sql=_CURSOR_SP,
        object_type=ProceduralObjectKind.PROCEDURE,
        schema_name="dbo",
        object_name="usp_BuildCustomerList_Bad",
        target_schema="public",
    )
    assert obj.success
    assert obj.postgres_syntax_valid
    assert not obj.errors
    assert _conversion_ready(obj)
    assert "FOR v_CustomerName IN" in obj.converted_sql


def test_conversion_ready_ignores_manual_review_flag():
    obj = ProceduralObjectResult(
        name="usp_a",
        schema_name="dbo",
        object_type=ProceduralObjectKind.PROCEDURE,
        success=True,
        converted_sql="CREATE OR REPLACE FUNCTION dbo.usp_a() RETURNS void LANGUAGE plpgsql AS $$ BEGIN NULL; END; $$;",
        postgres_syntax_valid=True,
        manual_review_required=True,
    )
    assert _conversion_ready(obj)


def test_conversion_ready_rejects_syntax_errors():
    obj = ProceduralObjectResult(
        name="usp_a",
        schema_name="dbo",
        object_type=ProceduralObjectKind.PROCEDURE,
        success=False,
        converted_sql="CREATE OR REPLACE FUNCTION dbo.usp_a() AS $$ BEGIN FOR r IN",
        postgres_syntax_valid=False,
        errors=["PostgreSQL syntax: syntax error at or near FOR"],
    )
    assert not _conversion_ready(obj)
