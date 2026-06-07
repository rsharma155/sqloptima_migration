# ruff: noqa: ARG002
"""
Module: sqlserver_watermark_adapter.py
Purpose: SQL Server watermark polling via parameterized queries (security-safe)
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from typing import Any

from apps.replicator.capture.models import TableInfo
from domains.replication.validators import validate_identifier
from infrastructure.replication.capture_provider_factory import ConfiguredWatermarkProvider
from shared.contracts.base_connector import DatabaseConnector
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)


class SqlServerWatermarkAdapter(ConfiguredWatermarkProvider):
    """Polls SQL Server using validated identifiers and bound parameters only."""

    def __init__(
        self,
        connector: DatabaseConnector,
        tables: list[TableInfo],
    ) -> None:
        super().__init__(tables)
        self._connector = connector

    async def _execute_query(
        self,
        schema: str,
        table_name: str,
        columns: list[str],
        watermark_column: str,
        last_value: str,
        batch_size: int,
    ) -> list[dict[str, Any]]:
        safe_schema = validate_identifier(schema)
        safe_table = validate_identifier(table_name)
        safe_wm = validate_identifier(watermark_column)
        # Identifiers are validated; values are always bound as parameters.
        sql = (
            f"SELECT TOP (?) * FROM [{safe_schema}].[{safe_table}] "
            f"WHERE [{safe_wm}] > ? ORDER BY [{safe_wm}]"
        )
        params = {"top": batch_size, "wm": last_value}
        try:
            rows = await self._connector.execute(sql, params)
            logger.debug(
                "watermark_poll_complete",
                schema=safe_schema,
                table=safe_table,
                row_count=len(rows),
            )
            return rows
        except Exception:
            logger.exception(
                "watermark_poll_failed",
                schema=safe_schema,
                table=safe_table,
            )
            return []
