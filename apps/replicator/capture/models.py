"""
Module: apps/replicator/capture/models.py
Purpose: Domain models for change data capture events, positions, and batch results
Author: Migration Platform Team
Created: 2026-05-22
Domain: Replication / Capture
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


class ChangeOperation(StrEnum):
    """Types of change data operations captured from the source."""

    INSERT = "INSERT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    UPDATE_MERGE = "UPDATEMERGE"


@dataclass(frozen=True)
class LsnPosition:
    """SQL Server Log Sequence Number represented as three hex segments.

    Compares naturally via tuple comparison of its three segments,
    enabling deterministic ordering of CDC events.
    """

    segment1: int
    segment2: int
    segment3: int

    @classmethod
    def from_string(cls, value: str) -> LsnPosition:
        clean = value.removeprefix("0x")
        parts = clean.split(":")
        return cls(
            segment1=int(parts[0], 16),
            segment2=int(parts[1], 16),
            segment3=int(parts[2], 16),
        )

    def to_string(self) -> str:
        return f"0x{self.segment1:08X}:{self.segment2:08X}:{self.segment3:04X}"

    def serialize(self) -> bytes:
        return struct.pack(">IIH", self.segment1, self.segment2, self.segment3)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, LsnPosition):
            return NotImplemented
        return (self.segment1, self.segment2, self.segment3) < (
            other.segment1,
            other.segment2,
            other.segment3,
        )

    def __le__(self, other: object) -> bool:
        if not isinstance(other, LsnPosition):
            return NotImplemented
        return (self.segment1, self.segment2, self.segment3) <= (
            other.segment1,
            other.segment2,
            other.segment3,
        )

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, LsnPosition):
            return NotImplemented
        return (self.segment1, self.segment2, self.segment3) > (
            other.segment1,
            other.segment2,
            other.segment3,
        )

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, LsnPosition):
            return NotImplemented
        return (self.segment1, self.segment2, self.segment3) >= (
            other.segment1,
            other.segment2,
            other.segment3,
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, LsnPosition):
            return NotImplemented
        return (
            self.segment1 == other.segment1
            and self.segment2 == other.segment2
            and self.segment3 == other.segment3
        )

    def __hash__(self) -> int:
        return hash((self.segment1, self.segment2, self.segment3))

    def __repr__(self) -> str:
        return f"LsnPosition({self.to_string()})"


@dataclass
class ChangeEvent:
    """A single row-level change captured from the source database.

    Carries all metadata needed for idempotent replay, including
    source LSN, transaction ID, and both before/after values.
    """

    table_schema: str
    table_name: str
    operation: ChangeOperation
    after_values: dict[str, Any] | None = None
    before_values: dict[str, Any] | None = None
    event_id: UUID = field(default_factory=uuid4)
    lsn: LsnPosition | None = None
    source_timestamp: datetime | None = None
    source_host: str = ""
    source_database: str = ""
    transaction_id: str = ""


@dataclass
class Watermark:
    """Tracks the last polled value for watermark-based incremental capture.

    Used by WatermarkProvider to resume polling from the correct position
    after restart.
    """

    table_schema: str
    table_name: str
    watermark_column: str
    last_value: str
    batch_size: int = 1000
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class WatermarkPosition:
    """Opaque position token for watermark-based capture providers.

    Stores the last-seen watermark value as UTF-8 bytes.  Compatible with the
    CaptureBatch.new_position interface (provides .serialize()).
    """

    raw_bytes: bytes

    def serialize(self) -> bytes:
        return self.raw_bytes

    @classmethod
    def from_value(cls, value: str) -> "WatermarkPosition":
        return cls(raw_bytes=value.encode())

    @classmethod
    def from_bytes(cls, data: bytes) -> "WatermarkPosition":
        return cls(raw_bytes=data)


@dataclass
class TableInfo:
    """Metadata about a source table being replicated."""

    schema_name: str
    table_name: str
    columns: list[str]
    pk_columns: list[str] = field(default_factory=list)
    row_count_estimate: int = 0
    capture_instance: str = ""
    watermark_column: str = ""
    # Fix 2.1: soft-delete column name; when set, rows with truthy value emit DELETE events
    soft_delete_column: str | None = None

    @property
    def qualified_name(self) -> str:
        return f"{self.schema_name}.{self.table_name}"


@dataclass
class CaptureBatch:
    """A batch of change events from a single poll cycle."""

    changes: list[ChangeEvent]
    new_position: LsnPosition
    change_count: int = 0

    def __post_init__(self) -> None:
        if self.change_count == 0:
            self.change_count = len(self.changes)


@dataclass
class SnapshotResult:
    """Result of a full table snapshot operation."""

    table_name: str
    rows_captured: int
    duration_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return len(self.errors) == 0
