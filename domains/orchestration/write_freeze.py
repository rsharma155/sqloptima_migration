"""Write-freeze coordination for cutover (§13.2).
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)


@dataclass
class WriteFreezeState:
    frozen: bool
    frozen_at: datetime | None = None
    source_row_counts: dict[str, int] | None = None
    message: str = ""


class WriteFreezeCoordinator:
    """Capture baseline row counts on source and detect post-freeze writes."""

    def __init__(self, source_connector: Any) -> None:
        self._source = source_connector

    async def freeze(self, schema: str, tables: list[str]) -> WriteFreezeState:
        counts: dict[str, int] = {}
        for table in tables:
            rows = await self._source.execute(
                f"SELECT COUNT(*) AS cnt FROM [{schema}].[{table}]"
            )
            counts[table] = rows[0]["cnt"] if rows else 0
        now = datetime.now(UTC)
        logger.info("write_freeze_applied", schema=schema, tables=tables, counts=counts)
        return WriteFreezeState(
            frozen=True,
            frozen_at=now,
            source_row_counts=counts,
            message="Baseline row counts captured — monitor source for new writes before cutover",
        )

    async def verify_no_new_writes(
        self,
        schema: str,
        baseline: dict[str, int],
        tolerance: int = 0,
    ) -> tuple[bool, dict[str, int]]:
        """Return (ok, current_counts). Fails if any table grew beyond tolerance."""
        current: dict[str, int] = {}
        for table, base_count in baseline.items():
            rows = await self._source.execute(
                f"SELECT COUNT(*) AS cnt FROM [{schema}].[{table}]"
            )
            current_count = rows[0]["cnt"] if rows else 0
            current[table] = current_count
            if current_count > base_count + tolerance:
                return False, current
        return True, current
