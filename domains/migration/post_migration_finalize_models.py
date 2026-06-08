"""
Module: post_migration_finalize_models.py
Purpose: Value objects for post-migration finalize lifecycle and options.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class FinalizeObjectStatus(StrEnum):
    PENDING = "pending"
    APPLIED = "applied"
    SKIPPED = "skipped"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"


class FinalizePhaseStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PostMigrationFinalizeOptions:
    """Operator-configurable finalize behaviour."""

    auto_finalize_after_validation: bool = True
    finalize_identities: bool = True
    finalize_indexes: bool = True
    finalize_foreign_keys: bool = True
    finalize_check_constraints: bool = True
    finalize_defaults: bool = True
    finalize_triggers: bool = False
    create_indexes_concurrently: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "auto_finalize_after_validation": self.auto_finalize_after_validation,
            "finalize_identities": self.finalize_identities,
            "finalize_indexes": self.finalize_indexes,
            "finalize_foreign_keys": self.finalize_foreign_keys,
            "finalize_check_constraints": self.finalize_check_constraints,
            "finalize_defaults": self.finalize_defaults,
            "finalize_triggers": self.finalize_triggers,
            "create_indexes_concurrently": self.create_indexes_concurrently,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> PostMigrationFinalizeOptions:
        if not data:
            return cls()
        return cls(
            auto_finalize_after_validation=bool(
                data.get("auto_finalize_after_validation", True)
            ),
            finalize_identities=bool(data.get("finalize_identities", True)),
            finalize_indexes=bool(data.get("finalize_indexes", True)),
            finalize_foreign_keys=bool(data.get("finalize_foreign_keys", True)),
            finalize_check_constraints=bool(data.get("finalize_check_constraints", True)),
            finalize_defaults=bool(data.get("finalize_defaults", True)),
            finalize_triggers=bool(data.get("finalize_triggers", False)),
            create_indexes_concurrently=bool(data.get("create_indexes_concurrently", False)),
        )


@dataclass
class FinalizeObjectResult:
    object_key: str
    object_type: str
    status: FinalizeObjectStatus
    message: str | None = None
    ddl: str | None = None


@dataclass
class FinalizeTableResult:
    table_name: str
    target_schema: str
    status: FinalizePhaseStatus = FinalizePhaseStatus.PENDING
    objects: list[FinalizeObjectResult] = field(default_factory=list)


@dataclass
class PostMigrationFinalizeState:
    status: FinalizePhaseStatus = FinalizePhaseStatus.PENDING
    tables: dict[str, dict[str, dict[str, str]]] = field(default_factory=dict)
    last_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "tables": self.tables,
            "last_error": self.last_error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> PostMigrationFinalizeState:
        if not data:
            return cls()
        try:
            status = FinalizePhaseStatus(data.get("status", FinalizePhaseStatus.PENDING))
        except ValueError:
            status = FinalizePhaseStatus.PENDING
        return cls(
            status=status,
            tables=dict(data.get("tables") or {}),
            last_error=data.get("last_error"),
        )

    def set_object_status(
        self,
        table_name: str,
        category: str,
        object_key: str,
        status: FinalizeObjectStatus,
    ) -> None:
        self.tables.setdefault(table_name, {}).setdefault(category, {})[object_key] = status.value
