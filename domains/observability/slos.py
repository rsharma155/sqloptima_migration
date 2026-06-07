"""Published SLO targets and capacity guidance (§13.12).
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ServiceSLO:
    name: str
    target: str
    measurement: str
    notes: str = ""


MIGRATION_SLOS: list[ServiceSLO] = [
    ServiceSLO(
        name="chunk_throughput",
        target="≥ 500,000 rows/hour/worker",
        measurement="rows_migrated / elapsed from /metrics",
        notes="Assumes indexed INT/BIGINT PK, 10k chunk size, local network",
    ),
    ServiceSLO(
        name="replication_lag",
        target="< 30 seconds p95",
        measurement="cdc_lag_seconds from replication metrics",
        notes="Polling CDC with watermark columns",
    ),
    ServiceSLO(
        name="validation_duration",
        target="≤ 50% of load time",
        measurement="validation_run_duration / migration_duration",
        notes="Row-count + aggregate validation on same hardware",
    ),
    ServiceSLO(
        name="api_availability",
        target="99.5% monthly",
        measurement="health check success rate",
        notes="Single-region deployment with restart:unless-stopped",
    ),
    ServiceSLO(
        name="cutover_rollback_window",
        target="24 hours retained checkpoint",
        measurement="cutover_checkpoints.committed=false age",
        notes="Operator must commit or rollback within window",
    ),
]


def capacity_table() -> list[dict[str, str]]:
    """Sizing guidance for operators."""
    return [
        {
            "table_size": "< 10M rows",
            "workers": "1–2",
            "chunk_size": "10,000",
            "expected_duration": "1–4 hours",
        },
        {
            "table_size": "10M–100M rows",
            "workers": "4–8",
            "chunk_size": "25,000",
            "expected_duration": "4–24 hours",
        },
        {
            "table_size": "100M–1B rows",
            "workers": "8–16",
            "chunk_size": "50,000",
            "expected_duration": "1–7 days",
        },
        {
            "table_size": "> 1B rows",
            "workers": "16+ (parallel tables)",
            "chunk_size": "100,000",
            "expected_duration": "Plan waves + LOB streaming",
        },
    ]
