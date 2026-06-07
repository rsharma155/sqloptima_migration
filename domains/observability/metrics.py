"""
Module: metrics.py
Purpose: Observability and metrics collection
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)

_MIGRATION_ROWS_TOTAL: dict[str, int] = {}
_MIGRATION_CHUNK_DURATION: list[float] = []
_MIGRATION_FAILURES_TOTAL: dict[str, int] = {}
_SOURCE_LATENCY: dict[str, float] = {}
_TARGET_LATENCY: dict[str, float] = {}
_QUEUE_LAG: float = 0.0
_ACTIVE_WORKERS: int = 0


def record_rows_migrated(table: str, count: int) -> None:
    _MIGRATION_ROWS_TOTAL[table] = _MIGRATION_ROWS_TOTAL.get(table, 0) + count
    logger.debug("Metrics: rows migrated", table=table, count=count, total=_MIGRATION_ROWS_TOTAL[table])


def get_rows_migrated(table: str | None = None) -> dict[str, int] | int:
    if table:
        return _MIGRATION_ROWS_TOTAL.get(table, 0)
    return dict(_MIGRATION_ROWS_TOTAL)


def record_chunk_duration(duration_ms: float) -> None:
    _MIGRATION_CHUNK_DURATION.append(duration_ms)
    if len(_MIGRATION_CHUNK_DURATION) > 10000:
        _MIGRATION_CHUNK_DURATION[:5000] = []
    logger.debug("Metrics: chunk duration", duration_ms=duration_ms)


def get_chunk_duration_stats() -> dict[str, float]:
    if not _MIGRATION_CHUNK_DURATION:
        return {"count": 0, "avg_ms": 0.0, "min_ms": 0.0, "max_ms": 0.0, "p95_ms": 0.0}
    sorted_durs = sorted(_MIGRATION_CHUNK_DURATION)
    count = len(sorted_durs)
    avg = sum(sorted_durs) / count
    p95_idx = int(count * 0.95)
    return {
        "count": count,
        "avg_ms": round(avg, 2),
        "min_ms": round(sorted_durs[0], 2),
        "max_ms": round(sorted_durs[-1], 2),
        "p95_ms": round(sorted_durs[p95_idx], 2),
    }


def record_failure(table: str) -> None:
    _MIGRATION_FAILURES_TOTAL[table] = _MIGRATION_FAILURES_TOTAL.get(table, 0) + 1
    logger.warning("Metrics: failure recorded", table=table, total=_MIGRATION_FAILURES_TOTAL[table])


def get_failures(table: str | None = None) -> dict[str, int] | int:
    if table:
        return _MIGRATION_FAILURES_TOTAL.get(table, 0)
    return dict(_MIGRATION_FAILURES_TOTAL)


def record_source_latency(table: str, latency_sec: float) -> None:
    _SOURCE_LATENCY[table] = latency_sec


def get_source_latency(table: str | None = None) -> dict[str, float] | float:
    if table:
        return _SOURCE_LATENCY.get(table, 0.0)
    return dict(_SOURCE_LATENCY)


def record_target_latency(table: str, latency_sec: float) -> None:
    _TARGET_LATENCY[table] = latency_sec


def get_target_latency(table: str | None = None) -> dict[str, float] | float:
    if table:
        return _TARGET_LATENCY.get(table, 0.0)
    return dict(_TARGET_LATENCY)


def set_queue_lag(lag_sec: float) -> None:
    global _QUEUE_LAG
    _QUEUE_LAG = lag_sec


def get_queue_lag() -> float:
    return _QUEUE_LAG


def set_active_workers(count: int) -> None:
    global _ACTIVE_WORKERS
    _ACTIVE_WORKERS = count


def get_active_workers() -> int:
    return _ACTIVE_WORKERS


class LatencyTracker:
    def __init__(self):
        self._source_start: dict[str, float] = {}
        self._target_start: dict[str, float] = {}

    def start_source_query(self, table: str) -> None:
        self._source_start[table] = time.perf_counter()

    def end_source_query(self, table: str) -> float:
        elapsed = time.perf_counter() - self._source_start.pop(table, time.perf_counter())
        record_source_latency(table, elapsed)
        return elapsed

    def start_target_write(self, table: str) -> None:
        self._target_start[table] = time.perf_counter()

    def end_target_write(self, table: str) -> float:
        elapsed = time.perf_counter() - self._target_start.pop(table, time.perf_counter())
        record_target_latency(table, elapsed)
        return elapsed


@dataclass
class MetricsSnapshot:
    rows_migrated: dict[str, int] = field(default_factory=dict)
    chunk_duration: dict[str, float] = field(default_factory=dict)
    failures: dict[str, int] = field(default_factory=dict)
    source_latency: dict[str, float] = field(default_factory=dict)
    target_latency: dict[str, float] = field(default_factory=dict)
    queue_lag: float = 0.0
    active_workers: int = 0


def snapshot() -> MetricsSnapshot:
    return MetricsSnapshot(
        rows_migrated=get_rows_migrated(),
        chunk_duration=get_chunk_duration_stats(),
        failures=get_failures(),
        source_latency=get_source_latency(),
        target_latency=get_target_latency(),
        queue_lag=get_queue_lag(),
        active_workers=get_active_workers(),
    )


def reset() -> None:
    _MIGRATION_ROWS_TOTAL.clear()
    _MIGRATION_CHUNK_DURATION.clear()
    _MIGRATION_FAILURES_TOTAL.clear()
    _SOURCE_LATENCY.clear()
    _TARGET_LATENCY.clear()
    global _QUEUE_LAG, _ACTIVE_WORKERS
    _QUEUE_LAG = 0.0
    _ACTIVE_WORKERS = 0
