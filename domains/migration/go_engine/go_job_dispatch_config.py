"""
Module: go_job_dispatch_config.py
Purpose: Serializable job dispatch contract stored in migration_jobs.config JSONB.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from domains.migration.go_engine.go_connection_dispatch_ref import GoConnectionDispatchRef
from domains.migration.go_engine.go_executor_kind import GoExecutorKind
from domains.migration.go_engine.go_table_dispatch_payload import GoTableDispatchPayload
from domains.migration.source_throttle import SourceThrottleConfig


@dataclass(frozen=True, slots=True)
class GoJobDispatchConfig:
    """Control-plane → Go data-plane handoff document (migration_jobs.config)."""

    job_id: UUID
    executor: GoExecutorKind
    source: GoConnectionDispatchRef
    target: GoConnectionDispatchRef
    tables: tuple[GoTableDispatchPayload, ...]
    snapshot_ref: str | None = None
    idempotent: bool = False
    conflict_columns: tuple[str, ...] = field(default_factory=tuple)
    use_nolock: bool = False
    source_throttle: SourceThrottleConfig = field(default_factory=SourceThrottleConfig)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "job_id": str(self.job_id),
            "executor": self.executor.value,
            "source": self.source.to_dict(),
            "target": self.target.to_dict(),
            "tables": [t.to_dict() for t in self.tables],
            "snapshot_ref": self.snapshot_ref,
            "idempotent": self.idempotent,
            "use_nolock": self.use_nolock,
            "source_throttle": self.source_throttle.to_dict(),
        }
        if self.conflict_columns:
            out["conflict_columns"] = list(self.conflict_columns)
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GoJobDispatchConfig:
        if data.get("executor") != GoExecutorKind.GO.value:
            raise ValueError(f"Unsupported executor in dispatch config: {data.get('executor')!r}")
        tables_raw = data.get("tables") or []
        conflict_raw = data.get("conflict_columns") or []
        return cls(
            job_id=UUID(str(data["job_id"])),
            executor=GoExecutorKind.GO,
            source=GoConnectionDispatchRef.from_dict(data["source"]),
            target=GoConnectionDispatchRef.from_dict(data["target"]),
            tables=tuple(GoTableDispatchPayload.from_dict(t) for t in tables_raw),
            snapshot_ref=data.get("snapshot_ref"),
            idempotent=bool(data.get("idempotent", False)),
            conflict_columns=tuple(str(c) for c in conflict_raw),
            use_nolock=bool(data.get("use_nolock", False)),
            source_throttle=SourceThrottleConfig.from_dict(data.get("source_throttle")),
        )

    def validate(self) -> None:
        """Raise ValueError when the contract is incomplete for the Go worker."""
        if not self.tables:
            raise ValueError("GoJobDispatchConfig requires at least one table")
        for table in self.tables:
            if not table.columns:
                raise ValueError(f"Table {table.table_name} has no resolved columns")
            if "*" in table.columns:
                raise ValueError(f"Table {table.table_name} must not use wildcard columns")
