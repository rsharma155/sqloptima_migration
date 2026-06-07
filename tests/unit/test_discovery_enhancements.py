"""
Module: tests/unit/test_discovery_enhancements.py
Purpose: Unit tests for Phase-4 SqlServerMetadataDiscovery enhancements —
         CDC status, linked-server references, and global temp table detection.
         Uses AsyncMock connectors to avoid needing a real SQL Server.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from infrastructure.sqlserver.sqlserver_discovery import SqlServerMetadataDiscovery


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_connector(execute_return: list) -> MagicMock:
    conn = MagicMock()
    conn.execute = AsyncMock(return_value=execute_return)
    return conn


def _make_discovery(execute_return: list) -> SqlServerMetadataDiscovery:
    connector = _make_connector(execute_return)
    discovery = SqlServerMetadataDiscovery(connector)
    discovery._database = "TestDB"
    return discovery


# ---------------------------------------------------------------------------
# CDC status
# ---------------------------------------------------------------------------


class TestCdcStatus:
    @pytest.mark.asyncio
    async def test_cdc_enabled_when_flag_true(self):
        discovery = _make_discovery([{"is_cdc_enabled": True}])
        # Second call for table status
        discovery._connector.execute = AsyncMock(
            side_effect=[
                [{"is_cdc_enabled": True}],
                [
                    {"table_name": "orders", "is_tracked_by_cdc": True},
                    {"table_name": "customers", "is_tracked_by_cdc": False},
                ],
            ]
        )
        result = await discovery.discover_cdc_status("TestDB", "dbo")
        assert result["db_cdc_enabled"] is True
        assert result["tables"]["orders"] is True
        assert result["tables"]["customers"] is False

    @pytest.mark.asyncio
    async def test_cdc_disabled_returns_false(self):
        discovery = _make_discovery([])
        discovery._connector.execute = AsyncMock(
            side_effect=[
                [{"is_cdc_enabled": False}],
                [],
            ]
        )
        result = await discovery.discover_cdc_status("TestDB", "dbo")
        assert result["db_cdc_enabled"] is False
        assert result["tables"] == {}

    @pytest.mark.asyncio
    async def test_empty_db_row_returns_false(self):
        discovery = _make_discovery([])
        discovery._connector.execute = AsyncMock(
            side_effect=[[], []]
        )
        result = await discovery.discover_cdc_status("TestDB", "dbo")
        assert result["db_cdc_enabled"] is False


# ---------------------------------------------------------------------------
# Linked server references
# ---------------------------------------------------------------------------


class TestLinkedServerRefs:
    @pytest.mark.asyncio
    async def test_linked_server_refs_returned(self):
        rows = [
            {
                "referencing_schema": "dbo",
                "referencing_object": "usp_fetch",
                "referenced_server": "REMOTE_SRV",
                "referenced_database": "OtherDB",
                "referenced_entity": "orders",
            }
        ]
        discovery = _make_discovery(rows)
        result = await discovery.discover_linked_server_refs("TestDB")
        assert len(result) == 1
        assert result[0]["referenced_server"] == "REMOTE_SRV"

    @pytest.mark.asyncio
    async def test_no_linked_server_refs_empty_list(self):
        discovery = _make_discovery([])
        result = await discovery.discover_linked_server_refs("TestDB")
        assert result == []

    @pytest.mark.asyncio
    async def test_multiple_linked_server_refs(self):
        rows = [
            {"referencing_schema": "dbo", "referencing_object": "usp_a",
             "referenced_server": "SRV1", "referenced_database": "DB1", "referenced_entity": "t1"},
            {"referencing_schema": "dbo", "referencing_object": "usp_b",
             "referenced_server": "SRV2", "referenced_database": "DB2", "referenced_entity": "t2"},
        ]
        discovery = _make_discovery(rows)
        result = await discovery.discover_linked_server_refs("TestDB")
        assert len(result) == 2
        servers = {r["referenced_server"] for r in result}
        assert "SRV1" in servers
        assert "SRV2" in servers


# ---------------------------------------------------------------------------
# Global temp table references
# ---------------------------------------------------------------------------


class TestGlobalTempTableRefs:
    @pytest.mark.asyncio
    async def test_global_temp_refs_returned(self):
        rows = [
            {"schema_name": "dbo", "object_name": "usp_process", "object_type": "SQL_STORED_PROCEDURE"}
        ]
        discovery = _make_discovery(rows)
        result = await discovery.discover_global_temp_table_refs("TestDB")
        assert len(result) == 1
        assert result[0]["object_name"] == "usp_process"

    @pytest.mark.asyncio
    async def test_no_global_temp_refs_empty_list(self):
        discovery = _make_discovery([])
        result = await discovery.discover_global_temp_table_refs("TestDB")
        assert result == []

    @pytest.mark.asyncio
    async def test_result_is_list_of_dicts(self):
        rows = [
            {"schema_name": "dbo", "object_name": "fn_build", "object_type": "SQL_SCALAR_FUNCTION"}
        ]
        discovery = _make_discovery(rows)
        result = await discovery.discover_global_temp_table_refs("TestDB")
        assert isinstance(result, list)
        assert isinstance(result[0], dict)
        assert "schema_name" in result[0]
        assert "object_name" in result[0]
