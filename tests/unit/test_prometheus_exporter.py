"""Unit tests for Prometheus metrics exposition."""
from __future__ import annotations

from domains.observability import metrics
from domains.observability.prometheus_exporter import render_prometheus


def test_render_prometheus_includes_counters():
    metrics.reset()
    metrics.record_rows_migrated("users", 1000)
    metrics.set_active_workers(4)
    text = render_prometheus()
    assert "migration_rows_total" in text
    assert 'table="users"' in text
    assert "migration_active_workers 4" in text
