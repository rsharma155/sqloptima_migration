"""
Module: source_throttle.py
Purpose: Configurable delay between source chunk extractions to reduce load on busy SQL Server.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SourceThrottleConfig:
    """Pause between consecutive chunk reads from SQL Server."""

    enabled: bool = True
    small_table_delay_sec: float = 1.0
    large_table_delay_sec: float = 4.0
    large_table_row_threshold: int = 100_000
    large_table_size_mb_threshold: float = 50.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "small_table_delay_sec": self.small_table_delay_sec,
            "large_table_delay_sec": self.large_table_delay_sec,
            "large_table_row_threshold": self.large_table_row_threshold,
            "large_table_size_mb_threshold": self.large_table_size_mb_threshold,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SourceThrottleConfig:
        if not data:
            return cls()
        return cls(
            enabled=bool(data.get("enabled", True)),
            small_table_delay_sec=float(data.get("small_table_delay_sec", 1.0)),
            large_table_delay_sec=float(data.get("large_table_delay_sec", 4.0)),
            large_table_row_threshold=int(data.get("large_table_row_threshold", 100_000)),
            large_table_size_mb_threshold=float(
                data.get("large_table_size_mb_threshold", 50.0)
            ),
        )
