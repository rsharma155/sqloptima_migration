"""
Module: entities.py
Purpose: Replication domain entities and value objects
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ConcernLevel = Literal["info", "warning", "blocker"]


@dataclass(frozen=True)
class StreamConcern:
    """A schema or operational concern surfaced before or during replication."""

    level: ConcernLevel
    message: str
    table_name: str | None = None
    property_name: str | None = None


@dataclass(frozen=True)
class StreamTableConfig:
    """Per-table replication configuration."""

    name: str
    watermark_column: str | None = None
    soft_delete_column: str | None = None
    pk_columns: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReplicationStreamConfig:
    """Immutable configuration for a replication stream."""

    stream_id: str
    name: str
    source_connection_id: str
    target_connection_id: str
    source_schema: str
    target_schema: str
    tables: list[StreamTableConfig]
    mode: str = "watermark"
    poll_interval_ms: int = 1000
    batch_size: int = 1000
