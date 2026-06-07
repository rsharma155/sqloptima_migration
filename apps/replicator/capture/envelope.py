"""
Module: envelope.py
Purpose: Serialize/deserialize ChangeEvent for message queue transport
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from apps.replicator.capture.models import ChangeEvent, ChangeOperation, LsnPosition


def event_to_envelope(event: ChangeEvent) -> dict[str, Any]:
    """Build the standard CDC message envelope."""
    return {
        "id": str(event.event_id),
        "timestamp": event.source_timestamp.isoformat() if event.source_timestamp else "",
        "source": {
            "type": "mssql",
            "host": event.source_host,
            "database": event.source_database,
            "lsn": event.lsn.to_string() if event.lsn else "",
            "txn_id": event.transaction_id,
        },
        "table": {
            "schema": event.table_schema,
            "name": event.table_name,
        },
        "operation": event.operation.value,
        "before": event.before_values,
        "after": event.after_values,
        "headers": {
            "schema_version": 1,
            "content_type": "application/json",
            "message_type": "change",
        },
    }


def event_from_envelope(
    payload: dict[str, Any],
    *,
    target_schema: str | None = None,
) -> ChangeEvent:
    """Reconstruct a ChangeEvent from a queue envelope."""
    table = payload.get("table") or {}
    source = payload.get("source") or {}
    lsn_raw = source.get("lsn") or ""
    lsn = LsnPosition.from_string(lsn_raw) if lsn_raw else None
    ts_raw = payload.get("timestamp") or ""
    ts = datetime.fromisoformat(ts_raw) if ts_raw else datetime.now(UTC)
    event_id_raw = payload.get("id")
    schema_name = target_schema or str(table.get("schema", "dbo"))
    return ChangeEvent(
        table_schema=schema_name,
        table_name=str(table.get("name", "")),
        operation=ChangeOperation(str(payload.get("operation", "INSERT"))),
        before_values=payload.get("before"),
        after_values=payload.get("after"),
        event_id=UUID(str(event_id_raw)) if event_id_raw else uuid4(),
        lsn=lsn,
        source_timestamp=ts,
        source_host=str(source.get("host", "")),
        source_database=str(source.get("database", "")),
        transaction_id=str(source.get("txn_id", "")),
    )
