"""
Module: test_metrics.py
Purpose: Unit tests
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import pytest

from domains.observability.metrics import (
    LatencyTracker,
    get_chunk_duration_stats,
    get_failures,
    get_rows_migrated,
    record_chunk_duration,
    record_failure,
    record_rows_migrated,
    reset,
    snapshot,
)


class TestMetrics:
    def setup_method(self):
        reset()

    def test_record_and_get_rows_migrated(self):
        record_rows_migrated("users", 100)
        record_rows_migrated("users", 50)
        record_rows_migrated("orders", 200)
        assert get_rows_migrated("users") == 150
        assert get_rows_migrated("orders") == 200
        all_rows = get_rows_migrated()
        assert all_rows["users"] == 150
        assert all_rows["orders"] == 200

    def test_record_and_get_chunk_duration(self):
        record_chunk_duration(100.0)
        record_chunk_duration(200.0)
        record_chunk_duration(300.0)
        stats = get_chunk_duration_stats()
        assert stats["count"] == 3
        assert stats["avg_ms"] == 200.0
        assert stats["min_ms"] == 100.0
        assert stats["max_ms"] == 300.0

    def test_chunk_duration_single_entry(self):
        record_chunk_duration(42.0)
        stats = get_chunk_duration_stats()
        assert stats["count"] == 1
        assert stats["avg_ms"] == 42.0

    def test_chunk_duration_empty(self):
        stats = get_chunk_duration_stats()
        assert stats["count"] == 0
        assert stats["avg_ms"] == 0.0

    def test_record_and_get_failures(self):
        record_failure("users")
        record_failure("users")
        record_failure("orders")
        assert get_failures("users") == 2
        assert get_failures("orders") == 1
        all_fails = get_failures()
        assert all_fails["users"] == 2

    def test_snapshot(self):
        record_rows_migrated("t", 50)
        record_chunk_duration(150.0)
        record_failure("t")
        s = snapshot()
        assert s.rows_migrated["t"] == 50
        assert s.chunk_duration["count"] == 1
        assert s.failures["t"] == 1

    def test_reset(self):
        record_rows_migrated("t", 100)
        record_failure("t")
        reset()
        assert get_rows_migrated("t") == 0
        assert get_failures("t") == 0
        assert get_chunk_duration_stats()["count"] == 0


class TestLatencyTracker:
    def test_tracks_source_latency(self):
        import time

        tracker = LatencyTracker()
        tracker.start_source_query("users")
        time.sleep(0.01)
        elapsed = tracker.end_source_query("users")
        assert elapsed > 0.005
        assert elapsed < 1.0

    def test_tracks_target_latency(self):
        import time

        tracker = LatencyTracker()
        tracker.start_target_write("users")
        time.sleep(0.01)
        elapsed = tracker.end_target_write("users")
        assert elapsed > 0.005
        assert elapsed < 1.0
