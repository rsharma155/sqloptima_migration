"""Unit tests for PostgreSQL routine deploy validation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from domains.migration.procedural_migration_models import ProceduralObjectKind
from domains.validation.postgres_routine_deploy_validator import (
    build_smoke_call_plan,
    deploy_and_verify_routine,
    split_sql_script,
)


class TestSplitSqlScript:
    def test_single_create_function(self):
        sql = (
            "CREATE OR REPLACE FUNCTION public.ufn_x() RETURNS integer "
            "LANGUAGE plpgsql AS $function$ BEGIN RETURN 1; END; $function$;"
        )
        parts = split_sql_script(sql)
        assert len(parts) == 1
        assert "CREATE OR REPLACE FUNCTION" in parts[0]

    def test_splits_multiple_statements(self):
        sql = "CREATE TYPE public.t AS (a int); SELECT 1;"
        parts = split_sql_script(sql)
        assert len(parts) == 2


class TestBuildSmokeCallPlan:
    def test_zero_arg_scalar_function(self):
        plan = build_smoke_call_plan(
            "public",
            "ufn_x",
            prokind="f",
            proretset=False,
            ret_type="int4",
            identity_args="",
        )
        assert plan.eligible
        assert plan.sql == 'SELECT "public"."ufn_x"();'

    def test_zero_arg_procedure(self):
        plan = build_smoke_call_plan(
            "public",
            "usp_x",
            prokind="p",
            proretset=False,
            ret_type="void",
            identity_args="",
        )
        assert plan.eligible
        assert plan.sql == 'CALL "public"."usp_x"();'

    def test_set_returning_function(self):
        plan = build_smoke_call_plan(
            "public",
            "tvf_x",
            prokind="f",
            proretset=True,
            ret_type="record",
            identity_args=None,
        )
        assert plan.eligible
        assert "SELECT * FROM" in plan.sql
        assert "LIMIT 0" in plan.sql

    def test_skips_when_required_arguments(self):
        plan = build_smoke_call_plan(
            "public",
            "ufn_x",
            prokind="f",
            proretset=False,
            ret_type="int4",
            identity_args="p_id integer",
        )
        assert not plan.eligible
        assert "requires arguments" in plan.skip_reason


def _mock_connector(conn: AsyncMock) -> MagicMock:
    tx = AsyncMock()
    tx.__aenter__ = AsyncMock(return_value=None)
    tx.__aexit__ = AsyncMock(return_value=None)
    conn.transaction = MagicMock(return_value=tx)

    pool = MagicMock()
    acquire_cm = AsyncMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=None)
    pool.acquire.return_value = acquire_cm

    connector = MagicMock()
    connector._pool = pool
    connector._config = MagicMock(statement_timeout_seconds=30.0)
    return connector


@pytest.mark.asyncio
async def test_deploy_and_verify_routine_success_with_smoke():
    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.fetchrow = AsyncMock(
        return_value={
            "oid": 123,
            "prokind": "f",
            "proretset": False,
            "ret_type": "int4",
            "identity_args": "",
            "regproc": "public.ufn_x()",
        }
    )
    connector = _mock_connector(conn)

    sql = (
        "CREATE OR REPLACE FUNCTION public.ufn_x() RETURNS integer "
        "LANGUAGE plpgsql AS $function$ BEGIN RETURN 1; END; $function$;"
    )
    result = await deploy_and_verify_routine(
        connector,
        sql=sql,
        target_schema="public",
        object_name="ufn_x",
        object_kind=ProceduralObjectKind.FUNCTION,
    )
    assert result.applied
    assert result.target_validated
    assert result.runtime_smoke_executed
    assert result.runtime_smoke_passed
    assert not result.errors
    assert conn.execute.await_count == 2


@pytest.mark.asyncio
async def test_deploy_and_verify_routine_skips_smoke_when_args_required():
    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.fetchrow = AsyncMock(
        return_value={
            "oid": 123,
            "prokind": "f",
            "proretset": False,
            "ret_type": "int4",
            "identity_args": "p_id integer",
            "regproc": "public.ufn_x(integer)",
        }
    )
    connector = _mock_connector(conn)

    result = await deploy_and_verify_routine(
        connector,
        sql="CREATE OR REPLACE FUNCTION public.ufn_x(p_id integer) RETURNS integer LANGUAGE sql AS $$ SELECT 1; $$;",
        target_schema="public",
        object_name="ufn_x",
        object_kind=ProceduralObjectKind.FUNCTION,
    )
    assert result.applied
    assert result.runtime_smoke_skipped
    assert not result.runtime_smoke_executed
    assert conn.execute.await_count == 1


@pytest.mark.asyncio
async def test_deploy_and_verify_routine_rolls_back_on_compile_error():
    conn = AsyncMock()
    conn.execute = AsyncMock(side_effect=Exception("syntax error at or near"))
    connector = _mock_connector(conn)

    result = await deploy_and_verify_routine(
        connector,
        sql="CREATE OR REPLACE FUNCTION public.bad() RETURNS integer LANGUAGE plpgsql AS $$ BEGIN $;",
        target_schema="public",
        object_name="bad",
        object_kind=ProceduralObjectKind.FUNCTION,
    )
    assert not result.applied
    assert not result.target_validated
    assert result.errors


@pytest.mark.asyncio
async def test_deploy_and_verify_routine_rolls_back_on_smoke_error():
    conn = AsyncMock()

    async def execute_side_effect(sql: str, timeout: float = 30.0) -> None:
        if sql.strip().upper().startswith("SELECT"):
            raise Exception("division by zero")

    conn.execute = AsyncMock(side_effect=execute_side_effect)
    conn.fetchrow = AsyncMock(
        return_value={
            "oid": 123,
            "prokind": "f",
            "proretset": False,
            "ret_type": "int4",
            "identity_args": "",
            "regproc": "public.ufn_x()",
        }
    )
    connector = _mock_connector(conn)

    result = await deploy_and_verify_routine(
        connector,
        sql="CREATE OR REPLACE FUNCTION public.ufn_x() RETURNS integer LANGUAGE plpgsql AS $$ BEGIN RETURN 1; END; $$;",
        target_schema="public",
        object_name="ufn_x",
        object_kind=ProceduralObjectKind.FUNCTION,
    )
    assert not result.applied
    assert "Runtime smoke call failed" in result.errors[0]
