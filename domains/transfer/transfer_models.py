"""
Module: transfer_models.py
Purpose: Transfer job status, table mapping, and runtime settings.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class TransferStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    PREPARING = "preparing"
    RUNNING = "running"
    PAUSED = "paused"
    RESTORING = "restoring"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    STOPPED = "stopped"
    RESTORE_FAILED = "restore_failed"


class TransferPhase(StrEnum):
    IDLE = "idle"
    PREPARING = "preparing"
    LOADING = "loading"
    RESTORING = "restoring"
    DONE = "done"


TERMINAL_STATUSES = frozenset({
    TransferStatus.COMPLETED,
    TransferStatus.PARTIAL,
    TransferStatus.FAILED,
    TransferStatus.STOPPED,
})

ACTIVE_STATUSES = frozenset({
    TransferStatus.QUEUED,
    TransferStatus.PREPARING,
    TransferStatus.RUNNING,
    TransferStatus.PAUSED,
    TransferStatus.RESTORING,
})


class TransferTableMapping(BaseModel):
    source_schema: str
    source_table: str
    target_schema: str
    target_table: str
    columns: list[str] = Field(default_factory=list)

    @property
    def source_key(self) -> str:
        return f"{self.source_schema}.{self.source_table}"

    @property
    def target_key(self) -> str:
        return f"{self.target_schema}.{self.target_table}"


class TransferThreshold(BaseModel):
    chunk_size: int = Field(default=10_000, ge=100, le=1_000_000)
    min_chunk_size: int = Field(default=1_000, ge=100, le=1_000_000)
    max_chunk_size: int = Field(default=100_000, ge=100, le=2_000_000)
    max_rows_per_sec: int | None = Field(default=None, ge=1)

    def clamped_chunk_size(self) -> int:
        lo = min(self.min_chunk_size, self.max_chunk_size)
        hi = max(self.min_chunk_size, self.max_chunk_size)
        return max(lo, min(self.chunk_size, hi))


class ConnectionEndpoint(BaseModel):
    connection_id: UUID
    engine: str
    host: str
    port: int
    database: str
    schema_name: str = ""

    def identity_tuple(self) -> tuple[str, int, str]:
        return (self.host.strip().lower(), int(self.port), self.database.strip().lower())


def same_database(source: ConnectionEndpoint, target: ConnectionEndpoint) -> bool:
    return source.identity_tuple() == target.identity_tuple()


def constraint_plan_default() -> dict[str, Any]:
    return {"on_stop": "restore_now", "create_if_missing": False, "tables": {}}
