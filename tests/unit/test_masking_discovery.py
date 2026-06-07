"""Tests for auto PII masking discovery (§12.2)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from domains.discovery.pii_classifier import SensitivityClass
from domains.migration.masking_discovery import discover_table_masking, merge_masking_profile
from shared.kernel.database_object import Column, DataType, Table


def _table(name: str, columns: list[str]) -> Table:
    return Table(
        database_name="db",
        schema_name="dbo",
        object_name=name,
        row_count_estimate=0,
        is_temporal=False,
        is_memory_optimized=False,
        columns=[
            Column(
                table_id=UUID(int=0),
                column_name=col,
                ordinal_position=i + 1,
                data_type=DataType(type_name="nvarchar", precision=None, scale=None, max_length=100, is_nullable=True),
                is_identity=False,
                is_computed=False,
                computed_definition=None,
                default_value=None,
                is_nullable=True,
                collation_name=None,
            )
            for i, col in enumerate(columns)
        ],
        index_count=len(columns),
    )


@pytest.mark.asyncio
async def test_discover_table_masking_flags_pii_columns():
    connector = AsyncMock()
    discovery = MagicMock()
    discovery.discover_tables = AsyncMock(
        return_value=[_table("users", ["id", "email", "first_name", "status"])]
    )

    import infrastructure.sqlserver.sqlserver_discovery as mod

    original = mod.SqlServerMetadataDiscovery
    mod.SqlServerMetadataDiscovery = MagicMock(return_value=discovery)
    try:
        profiles = await discover_table_masking(
            connector, database="db", schema="dbo", table_names=["users"]
        )
    finally:
        mod.SqlServerMetadataDiscovery = original

    profile = profiles["users"]
    assert profile.sensitive_count == 2
    assert profile.column_sensitivity["email"] == SensitivityClass.PII.value
    assert profile.column_sensitivity["first_name"] == SensitivityClass.PII.value
    assert "id" not in profile.column_sensitivity


def test_merge_masking_profile_auto_applies_discovered():
    from domains.migration.masking_discovery import TableMaskingProfile

    profile = TableMaskingProfile(
        table_name="users",
        column_sensitivity={"email": "pii"},
        column_types={"email": "nvarchar"},
        sensitive_count=1,
    )
    transforms, sensitivity = merge_masking_profile(
        profile,
        masking_policy="auto",
        column_transforms=None,
        column_sensitivity=None,
    )
    assert sensitivity == {"email": "pii"}
    assert transforms is None
