"""
Module: schema_drift_detector.py
Purpose: Detect schema drift between source and target tables for replication
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from dataclasses import dataclass

from domains.replication.entities import StreamConcern


@dataclass(frozen=True)
class TableSchemaSnapshot:
    """Lightweight column inventory for drift comparison."""

    schema_name: str
    table_name: str
    columns: list[str]
    pk_columns: list[str]


def detect_schema_drift(
    source: TableSchemaSnapshot,
    target: TableSchemaSnapshot | None,
) -> list[StreamConcern]:
    """Compare source vs target column sets and primary keys.

    Returns concerns ordered by severity (blocker → warning → info).
    """
    concerns: list[StreamConcern] = []
    table = source.table_name

    if target is None:
        concerns.append(StreamConcern(
            level="blocker",
            message=f"Table {table} is missing on target — run migration first",
            table_name=table,
        ))
        return concerns

    src_cols = {c.lower() for c in source.columns}
    tgt_cols = {c.lower() for c in target.columns}
    src_by_lower = {c.lower(): c for c in source.columns}
    tgt_by_lower = {c.lower(): c for c in target.columns}

    for missing in sorted(src_cols - tgt_cols):
        concerns.append(StreamConcern(
            level="warning",
            message=f"Column {src_by_lower[missing]} exists on source but not on target",
            table_name=table,
            property_name=f"column.{src_by_lower[missing]}",
        ))

    for extra in sorted(tgt_cols - src_cols):
        concerns.append(StreamConcern(
            level="info",
            message=f"Column {tgt_by_lower[extra]} exists on target only",
            table_name=table,
            property_name=f"column.{tgt_by_lower[extra]}",
        ))

    src_pk = {c.lower() for c in source.pk_columns}
    tgt_pk = {c.lower() for c in target.pk_columns}
    if src_pk and tgt_pk and src_pk != tgt_pk:
        concerns.append(StreamConcern(
            level="warning",
            message=(
                f"Primary key mismatch — source: {source.pk_columns}, "
                f"target: {target.pk_columns}"
            ),
            table_name=table,
            property_name="primary_key",
        ))

    return concerns
