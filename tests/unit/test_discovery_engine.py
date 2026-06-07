"""
Module: test_discovery_engine.py
Purpose: Unit tests for discovery engine
Author: Migration Platform Team
Created: 2026-05-22
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from domains.discovery.discovery_engine import DiscoveryEngine
from shared.contracts.base_connector import MetadataDiscoveryPort
from shared.kernel.database_object import DatabaseObject, DatabaseObjectType, Table


@pytest.fixture
def mock_discovery():
    discovery = MagicMock(spec=MetadataDiscoveryPort)

    discovery.discover_schemas = AsyncMock(
        return_value=[
            DatabaseObject(
                object_type=DatabaseObjectType.SCHEMA,
                database_name="test_db",
                schema_name="dbo",
                object_name="dbo",
            ),
            DatabaseObject(
                object_type=DatabaseObjectType.SCHEMA,
                database_name="test_db",
                schema_name="sales",
                object_name="sales",
            ),
        ]
    )

    discovery.discover_tables = AsyncMock(
        return_value=[
            Table(
                database_name="test_db",
                schema_name="dbo",
                object_name="users",
            ),
            Table(
                database_name="test_db",
                schema_name="dbo",
                object_name="orders",
            ),
        ]
    )

    discovery.discover_views = AsyncMock(return_value=[])
    discovery.discover_procedures = AsyncMock(return_value=[])
    discovery.discover_functions = AsyncMock(return_value=[])
    discovery.discover_dependencies = AsyncMock(return_value=[])

    return discovery


class TestDiscoveryEngine:
    @pytest.mark.asyncio
    async def test_discover_full_all_schemas(self, mock_discovery):
        engine = DiscoveryEngine(mock_discovery)
        result = await engine.discover_full("test_db")

        assert result.total_tables == 4
        assert result.total_objects == 4
        assert "test_db.dbo" in result.tables

    @pytest.mark.asyncio
    async def test_discover_full_specific_schema(self, mock_discovery):
        engine = DiscoveryEngine(mock_discovery)
        result = await engine.discover_full("test_db", schemas=["sales"])

        mock_discovery.discover_schemas.assert_not_called()
        assert "test_db.sales" in result.tables

    @pytest.mark.asyncio
    async def test_discovery_result_properties(self, mock_discovery):
        engine = DiscoveryEngine(mock_discovery)
        result = await engine.discover_full("test_db")

        assert isinstance(result.total_objects, int)
        assert isinstance(result.total_tables, int)

    @pytest.mark.asyncio
    async def test_discover_with_views_and_procedures(self, mock_discovery):
        mock_discovery.discover_views = AsyncMock(
            return_value=[
                DatabaseObject(
                    object_type=DatabaseObjectType.VIEW,
                    database_name="test_db",
                    schema_name="dbo",
                    object_name="v_users",
                )
            ]
        )
        mock_discovery.discover_procedures = AsyncMock(
            return_value=[
                DatabaseObject(
                    object_type=DatabaseObjectType.PROCEDURE,
                    database_name="test_db",
                    schema_name="dbo",
                    object_name="usp_get_users",
                )
            ]
        )

        engine = DiscoveryEngine(mock_discovery)
        result = await engine.discover_full("test_db")

        assert result.total_objects == 8
