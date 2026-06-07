"""Resolve effective platform migration settings (DB-backed).

Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from typing import Any

from apps.api.migration_settings_store import get_settings
from domains.migration.source_throttle import SourceThrottleConfig


def resolved_source_throttle() -> SourceThrottleConfig:
    stored = get_settings()
    return SourceThrottleConfig(
        enabled=bool(stored.get("source_throttle_enabled", True)),
        small_table_delay_sec=float(stored.get("small_table_delay_sec", 1.0)),
        large_table_delay_sec=float(stored.get("large_table_delay_sec", 4.0)),
        large_table_row_threshold=int(stored.get("large_table_row_threshold", 100_000)),
        large_table_size_mb_threshold=float(stored.get("large_table_size_mb_threshold", 50.0)),
    )


def get_max_tables_per_job() -> int:
    return int(get_settings().get("max_tables_per_job", 25))


def migration_settings_status() -> dict[str, Any]:
    stored = get_settings()
    throttle = resolved_source_throttle()
    return {
        "source_throttle_enabled": throttle.enabled,
        "small_table_delay_sec": throttle.small_table_delay_sec,
        "large_table_delay_sec": throttle.large_table_delay_sec,
        "large_table_row_threshold": throttle.large_table_row_threshold,
        "large_table_size_mb_threshold": throttle.large_table_size_mb_threshold,
        "max_tables_per_job": get_max_tables_per_job(),
        "updated_at": stored.get("updated_at") or None,
    }
