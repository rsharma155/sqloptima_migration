"""
Module: go_table_dispatch_payload.py
Purpose: Per-table payload embedded in GoJobDispatchConfig.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class GoTableDispatchPayload:
    """Resolved table plan sent to the Go migration-engine."""

    table_name: str
    source_schema: str
    target_schema: str
    columns: list[str]
    chunk_size: int
    parallel_workers: int
    strategy: str
    column_transforms: dict[str, str] = field(default_factory=dict)
    column_sensitivity: dict[str, str] = field(default_factory=dict)
    column_types: dict[str, str] = field(default_factory=dict)
    order_column: str | None = None
    where_clause: str | None = None
    source_maxdop: int = 1

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "table_name": self.table_name,
            "source_schema": self.source_schema,
            "target_schema": self.target_schema,
            "columns": list(self.columns),
            "chunk_size": self.chunk_size,
            "parallel_workers": self.parallel_workers,
            "strategy": self.strategy,
            "column_transforms": dict(self.column_transforms),
            "column_sensitivity": dict(self.column_sensitivity),
            "column_types": dict(self.column_types),
            "source_maxdop": self.source_maxdop,
        }
        if self.order_column:
            out["order_column"] = self.order_column
        if self.where_clause:
            out["where_clause"] = self.where_clause
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GoTableDispatchPayload:
        return cls(
            table_name=str(data["table_name"]),
            source_schema=str(data["source_schema"]),
            target_schema=str(data["target_schema"]),
            columns=[str(c) for c in data["columns"]],
            chunk_size=int(data["chunk_size"]),
            parallel_workers=int(data["parallel_workers"]),
            strategy=str(data["strategy"]),
            column_transforms={
                str(k): str(v) for k, v in (data.get("column_transforms") or {}).items()
            },
            column_sensitivity={
                str(k): str(v) for k, v in (data.get("column_sensitivity") or {}).items()
            },
            column_types={
                str(k): str(v) for k, v in (data.get("column_types") or {}).items()
            },
            order_column=(str(data["order_column"]) if data.get("order_column") else None),
            where_clause=(str(data["where_clause"]) if data.get("where_clause") else None),
            source_maxdop=int(data.get("source_maxdop", 1)),
        )
