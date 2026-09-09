"""
Module: transfer_dispatch_config.py
Purpose: Control-plane → Go data-plane handoff for Transfer jobs (transfer_jobs.config).
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from domains.transfer.transfer_path import TransferPath
from domains.transfer.transfer_settings import file_offload_snapshot

TRANSFER_KIND = "transfer"


@dataclass(frozen=True, slots=True)
class TransferConnectionRef:
    connection_id: UUID
    schema: str
    engine: str

    def to_dict(self) -> dict[str, str]:
        return {
            "connection_id": str(self.connection_id),
            "schema": self.schema,
            "engine": self.engine,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TransferConnectionRef:
        return cls(
            connection_id=UUID(str(data["connection_id"])),
            schema=str(data.get("schema") or ""),
            engine=str(data["engine"]),
        )


@dataclass(frozen=True, slots=True)
class TransferTablePayload:
    source_schema: str
    source_table: str
    target_schema: str
    target_table: str
    columns: tuple[str, ...]
    chunk_size: int = 10_000
    order_column: str | None = None
    row_count_estimate: int = 0

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "source_schema": self.source_schema,
            "source_table": self.source_table,
            "target_schema": self.target_schema,
            "target_table": self.target_table,
            "columns": list(self.columns),
            "chunk_size": self.chunk_size,
            "row_count_estimate": self.row_count_estimate,
        }
        if self.order_column:
            out["order_column"] = self.order_column
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TransferTablePayload:
        return cls(
            source_schema=str(data["source_schema"]),
            source_table=str(data["source_table"]),
            target_schema=str(data["target_schema"]),
            target_table=str(data["target_table"]),
            columns=tuple(str(c) for c in (data.get("columns") or ())),
            chunk_size=int(data.get("chunk_size") or 10_000),
            order_column=(str(data["order_column"]) if data.get("order_column") else None),
            row_count_estimate=int(data.get("row_count_estimate") or 0),
        )


@dataclass(frozen=True, slots=True)
class TransferDispatchConfig:
    """Serialized into transfer_jobs.config. Kind is always transfer."""

    job_id: UUID
    path: TransferPath
    source: TransferConnectionRef
    target: TransferConnectionRef
    tables: tuple[TransferTablePayload, ...]
    constraint_plan: dict[str, Any] = field(default_factory=dict)
    file_offload: dict[str, Any] = field(default_factory=file_offload_snapshot)
    kind: str = TRANSFER_KIND

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": str(self.job_id),
            "kind": TRANSFER_KIND,
            "path": self.path.value,
            "source": self.source.to_dict(),
            "target": self.target.to_dict(),
            "tables": [t.to_dict() for t in self.tables],
            "constraint_plan": dict(self.constraint_plan or {}),
            "file_offload": file_offload_snapshot(self.file_offload),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TransferDispatchConfig:
        if data.get("kind") != TRANSFER_KIND:
            raise ValueError(f"Unsupported dispatch kind: {data.get('kind')!r}")
        tables_raw = data.get("tables") or []
        return cls(
            job_id=UUID(str(data["job_id"])),
            path=TransferPath(str(data["path"])),
            source=TransferConnectionRef.from_dict(data["source"]),
            target=TransferConnectionRef.from_dict(data["target"]),
            tables=tuple(TransferTablePayload.from_dict(t) for t in tables_raw),
            constraint_plan=dict(data.get("constraint_plan") or {}),
            file_offload=file_offload_snapshot(data.get("file_offload")),
        )

    def validate(self) -> None:
        if not self.tables:
            raise ValueError("TransferDispatchConfig requires at least one table")
        for table in self.tables:
            if not table.columns:
                raise ValueError(f"Table {table.source_table} has no resolved columns")
            if "*" in table.columns:
                raise ValueError(f"Table {table.source_table} must not use wildcard columns")


def _columns_from_preflight(preflight: dict[str, Any] | None, source_schema: str, source_table: str) -> tuple[str, ...]:
    if not preflight:
        return ()
    key = f"{source_schema}.{source_table}".lower()
    for table in preflight.get("tables") or []:
        src = table.get("source") or {}
        if f"{src.get('schema')}.{src.get('table')}".lower() != key:
            continue
        matched = (table.get("columns") or {}).get("matched") or []
        names = tuple(str(c["name"]) for c in matched if c.get("name"))
        if names:
            return names
    return ()


def build_transfer_dispatch_config(
    *,
    job_id: UUID,
    path: TransferPath,
    source_connection_id: UUID,
    target_connection_id: UUID,
    source_engine: str,
    target_engine: str,
    tables: list[dict[str, Any]],
    threshold: dict[str, Any],
    constraint_plan: dict[str, Any],
    preflight: dict[str, Any] | None,
    file_offload: dict[str, Any] | None = None,
) -> TransferDispatchConfig:
    chunk_size = int(threshold.get("chunk_size") or 10_000)
    payloads: list[TransferTablePayload] = []
    for table in tables:
        requested = tuple(str(c) for c in (table.get("columns") or []) if c != "*")
        inferred = _columns_from_preflight(
            preflight, str(table["source_schema"]), str(table["source_table"]),
        )
        columns = requested or inferred
        order_column = columns[0] if columns else None
        payloads.append(
            TransferTablePayload(
                source_schema=str(table["source_schema"]),
                source_table=str(table["source_table"]),
                target_schema=str(table["target_schema"]),
                target_table=str(table["target_table"]),
                columns=columns,
                chunk_size=int(table.get("chunk_size") or chunk_size),
                order_column=order_column,
                row_count_estimate=int(table.get("row_count_estimate") or 0),
            )
        )
    source_schema = payloads[0].source_schema if payloads else ""
    target_schema = payloads[0].target_schema if payloads else ""
    cfg = TransferDispatchConfig(
        job_id=job_id,
        path=path,
        source=TransferConnectionRef(
            connection_id=source_connection_id, schema=source_schema, engine=source_engine,
        ),
        target=TransferConnectionRef(
            connection_id=target_connection_id, schema=target_schema, engine=target_engine,
        ),
        tables=tuple(payloads),
        constraint_plan=dict(constraint_plan or {}),
        file_offload=file_offload_snapshot(file_offload),
    )
    cfg.validate()
    return cfg
