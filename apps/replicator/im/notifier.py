"""
Module: notifier.py
Purpose: Change data capture replication pipeline
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def lag_alert(table: str, lag_seconds: float, threshold: float) -> str:
    return (
        "\U0001f6a8 Critical\n"
        f"\U0001f4a5 {table}: lag {lag_seconds:.0f}s (threshold {threshold:.0f}s)"
    )


def snapshot_complete(table: str, rows: int, duration: float) -> str:
    return (
        "\u2705 Info\n"
        f"\u2705 {table}: snapshot complete ({rows:,} rows in {duration:.0f}s)"
    )


def schema_drift_detected(table: str, changes: list[dict[str, Any]]) -> str:
    lines = [f"\u26a0\ufe0f Warning\n\u26a0\ufe0f {table}: schema drift detected"]
    for change in changes:
        change_type = change.get("type", "unknown")
        column = change.get("column", "?")
        lines.append(f"  - {change_type}: {column}")
    return "\n".join(lines)


def consumer_error(table: str, retries: int, dlq_count: int) -> str:
    return (
        "\U0001f6a8 Critical\n"
        f"\U0001f4a5 {table}: {retries} retries exhausted, {dlq_count} events in DLQ"
    )


def heartbeat(info: dict[str, Any]) -> str:
    items = "\n".join(f"  {k}: {v}" for k, v in info.items())
    return f"\u2139\ufe0f Debug\nHeartbeat:\n{items}"
