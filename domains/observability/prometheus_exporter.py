"""Prometheus text exposition format for platform metrics.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from domains.observability import metrics as m


def render_prometheus() -> str:
    """Render in-memory migration metrics as Prometheus text format."""
    lines: list[str] = []

    def _gauge(name: str, help_text: str, value: float, labels: dict[str, str] | None = None) -> None:
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} gauge")
        label_str = ""
        if labels:
            label_str = "{" + ",".join(f'{k}="{v}"' for k, v in labels.items()) + "}"
        lines.append(f"{name}{label_str} {value}")

    def _counter(name: str, help_text: str, value: float, labels: dict[str, str] | None = None) -> None:
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} counter")
        label_str = ""
        if labels:
            label_str = "{" + ",".join(f'{k}="{v}"' for k, v in labels.items()) + "}"
        lines.append(f"{name}{label_str} {value}")

    rows = m.get_rows_migrated()
    if isinstance(rows, dict):
        for table, count in rows.items():
            _counter("migration_rows_total", "Total rows migrated per table", count, {"table": table})

    failures = m.get_failures()
    if isinstance(failures, dict):
        for table, count in failures.items():
            _counter("migration_failures_total", "Migration failures per table", count, {"table": table})

    chunk_stats = m.get_chunk_duration_stats()
    if chunk_stats.get("count", 0) > 0:
        _gauge("migration_chunk_duration_avg_ms", "Average chunk duration in ms", chunk_stats["avg_ms"])
        _gauge("migration_chunk_duration_p95_ms", "P95 chunk duration in ms", chunk_stats["p95_ms"])

    _gauge("migration_queue_lag_seconds", "Replication queue lag in seconds", m.get_queue_lag())
    _gauge("migration_active_workers", "Active migration workers", m.get_active_workers())

    return "\n".join(lines) + "\n"
