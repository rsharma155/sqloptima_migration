"""
Module: test_orchestration_activities.py
Purpose: Unit tests
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from domains.orchestration.activities import (
    _get_approximate_row_count,
    _get_pk_columns,
    analyze_compatibility,
    convert_schema,
    discover_objects,
    migrate_table,
    plan_chunks,
    send_notification,
    validate_table,
)


class TestDiscoverObjects:
    @pytest.mark.asyncio
    @patch("domains.orchestration.activities._resolve_sqlserver_connector")
    @patch("infrastructure.sqlserver.sqlserver_discovery.SqlServerMetadataDiscovery")
    async def test_discover_all_types(self, MockDiscovery, MockResolve):
        mock_conn = AsyncMock()
        # The activity resolves its connector from the metadata DB; bypass that
        # lookup by stubbing the resolver to hand back a mock connector.
        MockResolve.return_value = mock_conn

        discovery = AsyncMock()
        MockDiscovery.return_value = discovery

        class FakeTable:
            object_id = 1
            object_name = "users"
            schema_name = "dbo"
            source_definition = "CREATE TABLE ..."

        class FakeView:
            object_id = 2
            object_name = "user_view"
            schema_name = "dbo"
            source_definition = "CREATE VIEW ..."

        class FakeProc:
            object_id = 3
            object_name = "sp_test"
            schema_name = "dbo"
            source_definition = "CREATE PROC ..."

        class FakeFunc:
            object_id = 4
            object_name = "fn_test"
            schema_name = "dbo"
            source_definition = "CREATE FUNCTION ..."

        discovery.discover_tables.return_value = [FakeTable()]
        discovery.discover_views.return_value = [FakeView()]
        discovery.discover_procedures.return_value = [FakeProc()]
        discovery.discover_functions.return_value = [FakeFunc()]

        result = await discover_objects("conn-1", "dbo")
        assert len(result) == 4
        assert result[0]["object_type"] == "TABLE"
        assert result[1]["object_type"] == "VIEW"
        assert result[2]["object_type"] == "PROCEDURE"
        assert result[3]["object_type"] == "FUNCTION"
        mock_conn.disconnect.assert_called_once()

    @pytest.mark.asyncio
    @patch("domains.orchestration.activities._resolve_sqlserver_connector")
    @patch("infrastructure.sqlserver.sqlserver_discovery.SqlServerMetadataDiscovery")
    async def test_disconnect_on_exception(self, MockDiscovery, MockResolve):
        mock_conn = AsyncMock()
        MockResolve.return_value = mock_conn
        discovery = AsyncMock()
        MockDiscovery.return_value = discovery
        discovery.discover_tables.side_effect = Exception("DB error")

        with pytest.raises(Exception, match="DB error"):
            await discover_objects("conn-1", "dbo")
        mock_conn.disconnect.assert_called_once()


class TestAnalyzeCompatibility:
    @pytest.mark.asyncio
    async def test_complex_procedure_not_compatible(self):
        objects = [
            {
                "object_id": "1",
                "object_type": "PROCEDURE",
                "name": "sp_complex",
                "source_definition": "DECLARE CURSOR FOR SELECT 1",
            }
        ]
        results = await analyze_compatibility(objects)
        assert len(results) == 1
        assert results[0]["compatible"] is False

    @pytest.mark.asyncio
    async def test_simple_select_is_compatible(self):
        objects = [
            {
                "object_id": "2",
                "object_type": "TABLE",
                "name": "users",
                "source_definition": "SELECT * FROM users",
            }
        ]
        results = await analyze_compatibility(objects)
        assert len(results) == 1
        assert results[0]["compatible"] is True

    @pytest.mark.asyncio
    async def test_empty_input(self):
        results = await analyze_compatibility([])
        assert results == []


class TestConvertSchema:
    @pytest.mark.asyncio
    async def test_successful_conversion(self):
        result = await convert_schema("obj-1", "SELECT 1")
        assert result["object_id"] == "obj-1"
        assert result["success"] is True
        assert "converted_sql" in result

    @pytest.mark.asyncio
    async def test_returns_warnings_and_errors(self):
        result = await convert_schema("obj-2", "SELECT * FROM users")
        assert "warnings" in result
        assert "errors" in result


class TestPlanChunks:
    @pytest.mark.asyncio
    @patch("domains.orchestration.activities._resolve_sqlserver_connector")
    async def test_plan_table_success(self, MockResolve):
        mock_conn = AsyncMock()
        MockResolve.return_value = mock_conn

        from domains.chunking.chunk_planner import ChunkBoundary, ChunkColumnType, ChunkPlan

        with patch("domains.orchestration.activities.ChunkPlanner") as MockPlanner:
            mock_planner = AsyncMock()
            MockPlanner.return_value = mock_planner
            mock_planner.plan_table.return_value = MagicMock(
                column_name="id",
                column_type=ChunkColumnType.IDENTITY_PK,
                total_rows_estimate=5000,
                min_value=1,
                max_value=5000,
                chunks=[
                    ChunkPlan(
                        table_schema="dbo", table_name="users",
                        boundary=ChunkBoundary(start=1, end=2500),
                        column_name="id", column_type=ChunkColumnType.IDENTITY_PK,
                    ),
                    ChunkPlan(
                        table_schema="dbo", table_name="users",
                        boundary=ChunkBoundary(start=2501, end=5000),
                        column_name="id", column_type=ChunkColumnType.IDENTITY_PK,
                    ),
                ],
            )

            result = await plan_chunks("conn-1", "dbo", "users", 5000)
        assert result["status"] == "planned"
        assert result["total_chunks"] == 2
        assert result["total_rows_estimate"] == 5000
        mock_conn.disconnect.assert_called_once()

    @pytest.mark.asyncio
    @patch("domains.orchestration.activities._resolve_sqlserver_connector")
    async def test_plan_table_disconnect_on_error(self, MockResolve):
        mock_conn = AsyncMock()
        MockResolve.return_value = mock_conn

        with patch("domains.orchestration.activities.ChunkPlanner") as MockPlanner:
            mock_planner = AsyncMock()
            MockPlanner.return_value = mock_planner
            mock_planner.plan_table.side_effect = Exception("Plan failed")

            with pytest.raises(Exception, match="Plan failed"):
                await plan_chunks("conn-1", "dbo", "users", 5000)
            mock_conn.disconnect.assert_called_once()


class TestMigrateTable:
    @pytest.mark.asyncio
    async def test_migrate_success(self):
        from domains.chunking.chunk_planner import ChunkBoundary, ChunkColumnType, ChunkPlan

        mock_source = AsyncMock()
        mock_target = AsyncMock()

        mock_planner = AsyncMock()
        mock_planner.plan_table.return_value = MagicMock(
            column_name="id",
            column_type=ChunkColumnType.IDENTITY_PK,
            chunks=[
                ChunkPlan(
                    table_schema="dbo", table_name="users",
                    boundary=ChunkBoundary(start=1, end=100),
                    column_name="id", column_type=ChunkColumnType.IDENTITY_PK,
                ),
            ],
        )

        with (
            patch("domains.orchestration.activities._resolve_sqlserver_connector") as MockSrc,
            patch("domains.orchestration.activities._resolve_postgres_connector") as MockTgt,
            patch("domains.orchestration.activities.ChunkPlanner") as MockPlannerCls,
        ):
            MockSrc.return_value = mock_source
            MockTgt.return_value = mock_target
            MockPlannerCls.return_value = mock_planner

            mock_source.execute.side_effect = [
                [{"column_name": "id"}],
                [{"row_count": 100}],
                [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}],
            ]
            mock_target.copy_from_rows.return_value = 2

            result = await migrate_table("src", "tgt", "dbo", "users", ["id", "name"], 100, 4)
        assert result["status"] == "completed"
        assert result["rows_migrated"] == 2

    @pytest.mark.asyncio
    async def test_migrate_nothing_when_no_chunks(self):
        mock_source = AsyncMock()
        mock_target = AsyncMock()

        with (
            patch("domains.orchestration.activities._resolve_sqlserver_connector") as MockSrc,
            patch("domains.orchestration.activities._resolve_postgres_connector") as MockTgt,
            patch("domains.orchestration.activities.ChunkPlanner") as MockPlannerCls,
        ):
            MockSrc.return_value = mock_source
            MockTgt.return_value = mock_target

            mock_planner = AsyncMock()
            mock_planner.plan_table.return_value = MagicMock(chunks=[])
            MockPlannerCls.return_value = mock_planner

            mock_source.execute.side_effect = [
                [{"column_name": "id"}],
                [{"row_count": 0}],
            ]

            result = await migrate_table("src", "tgt", "dbo", "empty", ["id"], 100, 4)
        assert result["status"] == "completed"
        assert result["rows_migrated"] == 0

    @pytest.mark.asyncio
    async def test_migrate_returns_error_on_exception(self):
        with (
            patch("domains.orchestration.activities._resolve_sqlserver_connector") as MockSrc,
            patch("domains.orchestration.activities._resolve_postgres_connector") as MockTgt,
        ):
            MockSrc.side_effect = Exception("Connection broken")
            MockTgt.return_value = AsyncMock()

            result = await migrate_table("src", "tgt", "dbo", "failing", ["id"], 100, 4)
        assert result["status"] == "failed"
        assert "Connection broken" in result["error"]


class TestValidateTable:
    @pytest.mark.asyncio
    async def test_counts_match(self):
        mock_source = AsyncMock()
        mock_target = AsyncMock()

        with (
            patch("domains.orchestration.activities._resolve_sqlserver_connector") as MockSrc,
            patch("domains.orchestration.activities._resolve_postgres_connector") as MockTgt,
        ):
            MockSrc.return_value = mock_source
            MockTgt.return_value = mock_target

            mock_source.execute.return_value = [{"row_count": 100}]
            mock_target.execute.return_value = [{"cnt": 100}]

            result = await validate_table("src", "tgt", "dbo", "users")
        assert result["status"] == "passed"
        assert result["source_count"] == 100
        assert result["target_count"] == 100

    @pytest.mark.asyncio
    async def test_counts_mismatch(self):
        mock_source = AsyncMock()
        mock_target = AsyncMock()

        with (
            patch("domains.orchestration.activities._resolve_sqlserver_connector") as MockSrc,
            patch("domains.orchestration.activities._resolve_postgres_connector") as MockTgt,
        ):
            MockSrc.return_value = mock_source
            MockTgt.return_value = mock_target

            mock_source.execute.return_value = [{"row_count": 1000}]
            mock_target.execute.return_value = [{"cnt": 500}]

            result = await validate_table("src", "tgt", "dbo", "users")
        assert result["status"] == "failed"
        assert result["source_count"] == 1000
        assert result["target_count"] == 500

    @pytest.mark.asyncio
    async def test_uses_expected_row_count_from_metadata(self):
        mock_source = AsyncMock()
        mock_target = AsyncMock()

        with (
            patch("domains.orchestration.activities._resolve_sqlserver_connector") as MockSrc,
            patch("domains.orchestration.activities._resolve_postgres_connector") as MockTgt,
        ):
            MockSrc.return_value = mock_source
            MockTgt.return_value = mock_target
            mock_target.execute.return_value = [{"cnt": 250}]

            result = await validate_table(
                "src", "tgt", "dbo", "users", expected_row_count=250,
            )
        assert result["status"] == "passed"
        assert result["source_count_basis"] == "migration_metadata"
        MockSrc.assert_not_called()
        mock_source.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_resolve_sqlserver_connector_applies_trust_certificate(self):
        resolved = {
            "host": "localhost",
            "port": 1433,
            "database": "db",
            "username": "sa",
            "password": "pw",
            "ssl_enabled": True,
            "trust_server_certificate": True,
        }
        with (
            patch(
                "application.workflow_bridge_service.WorkflowBridgeService",
            ) as MockBridge,
            patch(
                "infrastructure.sqlserver.sqlserver_connector.SqlServerConnector",
            ) as MockConnector,
            patch(
                "infrastructure.sqlserver.sqlserver_connector.sqlserver_config_from_resolved",
            ) as mock_cfg_fn,
        ):
            mock_cfg_fn.return_value = MagicMock()
            bridge = MockBridge.return_value
            bridge.resolve_connection = AsyncMock(return_value=resolved)
            MockConnector.return_value.connect = AsyncMock()

            from domains.orchestration.activities import _resolve_sqlserver_connector

            await _resolve_sqlserver_connector("conn-id", "Sales")

        mock_cfg_fn.assert_called_once_with(
            resolved,
            password="pw",
            schema="Sales",
        )

    @pytest.mark.asyncio
    async def test_error_returns_status_error(self):
        mock_source = AsyncMock()
        mock_target = AsyncMock()
        mock_target.execute.side_effect = Exception("Target unreachable")

        with (
            patch("domains.orchestration.activities._resolve_sqlserver_connector") as MockSrc,
            patch("domains.orchestration.activities._resolve_postgres_connector") as MockTgt,
        ):
            MockSrc.return_value = mock_source
            MockTgt.return_value = mock_target

            result = await validate_table("src", "tgt", "dbo", "users")
        assert result["status"] == "error"
        assert "Target unreachable" in result["error"]


class TestHelpers:
    @pytest.mark.asyncio
    async def test_get_pk_columns_returns_list(self):
        source = AsyncMock()
        source.execute.return_value = [{"column_name": "id"}, {"column_name": "tenant_id"}]
        cols = await _get_pk_columns(source, "dbo", "orders")
        assert cols == ["id", "tenant_id"]

    @pytest.mark.asyncio
    async def test_get_pk_columns_empty_on_error(self):
        source = AsyncMock()
        source.execute.side_effect = Exception("query failed")
        cols = await _get_pk_columns(source, "dbo", "orders")
        assert cols == []

    @pytest.mark.asyncio
    async def test_get_approximate_row_count_from_partitions(self):
        source = AsyncMock()
        source.execute.return_value = [{"row_count": 5000}]
        count = await _get_approximate_row_count(source, "dbo", "orders")
        assert count == 5000

    @pytest.mark.asyncio
    async def test_get_approximate_row_count_falls_back_to_count(self):
        source = AsyncMock()
        source.execute.side_effect = [
            Exception("partitions fail"),
            [{"cnt": 42}],
        ]
        count = await _get_approximate_row_count(source, "dbo", "orders")
        assert count == 42

    @pytest.mark.asyncio
    async def test_get_approximate_row_count_zero_on_all_fail(self):
        source = AsyncMock()
        source.execute.side_effect = Exception("all fail")
        count = await _get_approximate_row_count(source, "dbo", "orders")
        assert count == 0


class TestSendNotification:
    @pytest.mark.asyncio
    async def test_logs_and_returns_none(self):
        result = await send_notification("console", "hello")
        assert result is None
