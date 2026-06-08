"""
Module: procedural_migration_models.py
Purpose: Domain models for stored procedure / function migration state.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ProceduralObjectKind(StrEnum):
    PROCEDURE = "procedure"
    FUNCTION = "function"


class ProceduralMigrateStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    APPLIED = "applied"
    FAILED = "failed"
    SKIPPED = "skipped"


class ProceduralMigrationPhaseStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class ProceduralObjectSelection:
    name: str
    object_type: ProceduralObjectKind

    @classmethod
    def from_name(cls, name: str, object_type: str) -> ProceduralObjectSelection:
        kind = ProceduralObjectKind.PROCEDURE
        raw = object_type.lower()
        if raw in {"function", "scalar_function", "table_function", "inline_function"}:
            kind = ProceduralObjectKind.FUNCTION
        return cls(name=name.strip(), object_type=kind)


@dataclass
class ProceduralObjectResult:
    name: str
    schema_name: str
    object_type: ProceduralObjectKind
    status: ProceduralMigrateStatus = ProceduralMigrateStatus.PENDING
    success: bool = False
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    manual_review_required: bool = False
    postgres_syntax_valid: bool = True
    target_validated: bool = False
    runtime_smoke_executed: bool = False
    runtime_smoke_passed: bool = False
    runtime_smoke_skipped: bool = False
    runtime_smoke_message: str = ""
    converted_sql: str = ""

    @property
    def object_key(self) -> str:
        return f"{self.schema_name}.{self.name}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "schema_name": self.schema_name,
            "object_type": self.object_type.value,
            "status": self.status.value,
            "success": self.success,
            "warnings": self.warnings,
            "errors": self.errors,
            "manual_review_required": self.manual_review_required,
            "postgres_syntax_valid": self.postgres_syntax_valid,
            "target_validated": self.target_validated,
            "runtime_smoke_executed": self.runtime_smoke_executed,
            "runtime_smoke_passed": self.runtime_smoke_passed,
            "runtime_smoke_skipped": self.runtime_smoke_skipped,
            "runtime_smoke_message": self.runtime_smoke_message,
            "converted_sql": self.converted_sql,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProceduralObjectResult:
        return cls(
            name=str(data.get("name", "")),
            schema_name=str(data.get("schema_name", "dbo")),
            object_type=ProceduralObjectKind(str(data.get("object_type", "procedure"))),
            status=ProceduralMigrateStatus(str(data.get("status", "pending"))),
            success=bool(data.get("success", False)),
            warnings=list(data.get("warnings") or []),
            errors=list(data.get("errors") or []),
            manual_review_required=bool(data.get("manual_review_required", False)),
            postgres_syntax_valid=bool(data.get("postgres_syntax_valid", True)),
            target_validated=bool(data.get("target_validated", False)),
            runtime_smoke_executed=bool(data.get("runtime_smoke_executed", False)),
            runtime_smoke_passed=bool(data.get("runtime_smoke_passed", False)),
            runtime_smoke_skipped=bool(data.get("runtime_smoke_skipped", False)),
            runtime_smoke_message=str(data.get("runtime_smoke_message") or ""),
            converted_sql=str(data.get("converted_sql") or ""),
        )


@dataclass
class ProceduralMigrationState:
    source_schema: str = "dbo"
    target_schema: str = "public"
    selected_procedures: list[str] = field(default_factory=list)
    selected_functions: list[str] = field(default_factory=list)
    auto_migrate_after_tables: bool = True
    status: ProceduralMigrationPhaseStatus = ProceduralMigrationPhaseStatus.PENDING
    last_error: str | None = None
    objects: dict[str, ProceduralObjectResult] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_schema": self.source_schema,
            "target_schema": self.target_schema,
            "selected_procedures": self.selected_procedures,
            "selected_functions": self.selected_functions,
            "auto_migrate_after_tables": self.auto_migrate_after_tables,
            "status": self.status.value,
            "last_error": self.last_error,
            "objects": {k: v.to_dict() for k, v in self.objects.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ProceduralMigrationState:
        if not data:
            return cls()
        objects_raw = data.get("objects") or {}
        return cls(
            source_schema=str(data.get("source_schema") or "dbo"),
            target_schema=str(data.get("target_schema") or "public"),
            selected_procedures=list(data.get("selected_procedures") or []),
            selected_functions=list(data.get("selected_functions") or []),
            auto_migrate_after_tables=bool(data.get("auto_migrate_after_tables", True)),
            status=ProceduralMigrationPhaseStatus(
                str(data.get("status") or ProceduralMigrationPhaseStatus.PENDING.value)
            ),
            last_error=data.get("last_error"),
            objects={
                str(k): ProceduralObjectResult.from_dict(v)
                for k, v in objects_raw.items()
            },
        )

    def selected_objects(self) -> list[ProceduralObjectSelection]:
        out: list[ProceduralObjectSelection] = []
        for name in self.selected_procedures:
            out.append(ProceduralObjectSelection(name=name, object_type=ProceduralObjectKind.PROCEDURE))
        for name in self.selected_functions:
            out.append(ProceduralObjectSelection(name=name, object_type=ProceduralObjectKind.FUNCTION))
        return out

    def has_selection(self) -> bool:
        return bool(self.selected_procedures or self.selected_functions)
