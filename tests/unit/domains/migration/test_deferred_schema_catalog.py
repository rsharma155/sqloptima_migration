"""
Module: test_deferred_schema_catalog.py
Purpose: Unit tests for deferred post-migration schema catalog discovery.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import pytest

from domains.migration.deferred_schema_catalog import (
    DeferredSchemaCatalogBuilder,
    DeferredTableSchema,
    catalog_from_dict,
    catalog_to_dict,
)


class FakeConnector:
    def __init__(self, responses: dict[str, list[dict]]):
        self._responses = responses
        self.queries: list[str] = []

    async def execute(self, query: str, *args, **kwargs):
        self.queries.append(query)
        for key, rows in self._responses.items():
            if key in query:
                return rows
        return []


@pytest.mark.asyncio
async def test_build_catalog_captures_identity_and_secondary_index():
    connector = FakeConnector(
        {
            "sys.identity_columns": [
                {
                    "column_name": "HotelID",
                    "type_name": "int",
                    "seed_value": 1,
                    "increment_value": 1,
                    "last_value": 500,
                }
            ],
            "sys.indexes": [
                {
                    "index_name": "PK__Hotels",
                    "is_unique": True,
                    "is_primary_key": True,
                    "is_clustered": True,
                    "index_type": 1,
                    "filter_definition": None,
                    "column_name": "HotelID",
                    "is_included": False,
                    "key_ordinal": 1,
                },
                {
                    "index_name": "IX_Hotels_Country",
                    "is_unique": False,
                    "is_primary_key": False,
                    "is_clustered": False,
                    "index_type": 2,
                    "filter_definition": None,
                    "column_name": "Country",
                    "is_included": False,
                    "key_ordinal": 1,
                },
            ],
            "sys.foreign_keys": [],
            "sys.check_constraints": [],
            "sys.triggers": [],
            "sys.columns dc": [],
        }
    )

    builder = DeferredSchemaCatalogBuilder(connector)
    catalog = await builder.build_for_table(
        source_schema="dbo",
        table_name="Hotels",
        target_schema="public",
    )

    assert len(catalog.identity_columns) == 1
    assert catalog.identity_columns[0].column_name == "HotelID"
    assert catalog.identity_columns[0].seed_value == 1
    assert len(catalog.secondary_indexes) == 1
    assert catalog.secondary_indexes[0].index_name == "IX_Hotels_Country"
    assert all(not idx.is_primary_key for idx in catalog.secondary_indexes)


@pytest.mark.asyncio
async def test_build_catalog_marks_columnstore_index_unsupported():
    connector = FakeConnector(
        {
            "sys.identity_columns": [],
            "sys.indexes": [
                {
                    "index_name": "CCI_Hotels",
                    "is_unique": False,
                    "is_primary_key": False,
                    "is_clustered": True,
                    "index_type": 5,
                    "filter_definition": None,
                    "column_name": "HotelID",
                    "is_included": False,
                    "key_ordinal": 1,
                },
            ],
            "sys.foreign_keys": [],
            "sys.check_constraints": [],
            "sys.triggers": [],
            "sys.columns dc": [],
        }
    )

    builder = DeferredSchemaCatalogBuilder(connector)
    catalog = await builder.build_for_table("dbo", "Hotels", "public")

    assert len(catalog.secondary_indexes) == 1
    assert catalog.secondary_indexes[0].unsupported_reason is not None


@pytest.mark.asyncio
async def test_catalog_roundtrip_serialization():
    catalog = DeferredTableSchema(
        source_schema="dbo",
        table_name="Hotels",
        target_schema="public",
    )
    data = catalog_to_dict(catalog)
    restored = catalog_from_dict(data)
    assert restored.table_name == "Hotels"
    assert restored.source_schema == "dbo"
