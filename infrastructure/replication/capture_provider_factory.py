"""
Module: capture_provider_factory.py
Purpose: Build SQL Server watermark capture providers from stream configuration
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from apps.replicator.capture.models import TableInfo
from apps.replicator.capture.providers.watermark_provider import WatermarkProvider

QueryFn = Callable[..., Awaitable[list[dict[str, Any]]]]


class ConfiguredWatermarkProvider(WatermarkProvider):
    """Watermark provider scoped to an explicit table list."""

    def __init__(
        self,
        tables: list[TableInfo],
        *,
        query_fn: QueryFn | None = None,
    ) -> None:
        super().__init__()
        self._configured_tables = tables
        self._query_fn = query_fn

    async def _fetch_table_list(self, schema: str) -> list[TableInfo]:
        return [t for t in self._configured_tables if t.schema_name == schema]

    async def _execute_query(
        self,
        schema: str,
        table_name: str,
        columns: list[str],
        watermark_column: str,
        last_value: str,
        batch_size: int,
    ) -> list[dict[str, Any]]:
        if self._query_fn is not None:
            return await self._query_fn(
                schema=schema,
                table_name=table_name,
                columns=columns,
                watermark_column=watermark_column,
                last_value=last_value,
                batch_size=batch_size,
            )
        return []


def build_table_infos(
    *,
    schema: str,
    table_names: list[str],
    pk_map: dict[str, list[str]] | None = None,
    watermark_map: dict[str, str] | None = None,
) -> list[TableInfo]:
    """Construct TableInfo rows from validated table names."""
    pk_map = pk_map or {}
    watermark_map = watermark_map or {}
    out: list[TableInfo] = []
    for name in table_names:
        out.append(TableInfo(
            schema_name=schema,
            table_name=name,
            columns=["*"],
            pk_columns=pk_map.get(name.lower(), ["id"]),
            watermark_column=watermark_map.get(name.lower(), "modified"),
        ))
    return out
