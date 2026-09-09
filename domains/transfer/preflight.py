"""
Module: preflight.py
Purpose: Pure comparison of source/target table inventories for Transfer.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from domains.transfer.transfer_path import TransferPath, is_homogeneous

Severity = Literal["blocker", "warning", "info", "ok"]


_TYPE_ALIASES = {
    "character varying": "varchar",
    "character": "char",
    "national character varying": "varchar",
    "national character": "char",
    "integer": "int",
    "int4": "int",
    "int8": "bigint",
    "int2": "smallint",
    "bool": "boolean",
    "timestamptz": "timestamp with time zone",
    "datetime2": "datetime",
    "nvarchar": "varchar",
    "nchar": "char",
    "sysname": "varchar",
    "float8": "double precision",
    "float4": "real",
    "numeric": "decimal",
}


@dataclass(slots=True)
class ColumnInventory:
    name: str
    type_name: str
    nullable: bool
    is_identity: bool = False


@dataclass(slots=True)
class ObjectInventory:
    object_id: str
    kind: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TableInventory:
    schema: str
    table: str
    exists: bool
    row_count: int = 0
    columns: list[ColumnInventory] = field(default_factory=list)
    constraints: list[ObjectInventory] = field(default_factory=list)
    indexes: list[ObjectInventory] = field(default_factory=list)
    foreign_keys: list[ObjectInventory] = field(default_factory=list)
    triggers: list[ObjectInventory] = field(default_factory=list)


def normalize_type(type_name: str) -> str:
    raw = (type_name or "").strip().lower()
    if "(" in raw:
        raw = raw.split("(", 1)[0].strip()
    return _TYPE_ALIASES.get(raw, raw)


def compare_table(
    *,
    path: TransferPath,
    source: TableInventory,
    target: TableInventory,
    create_if_missing: bool,
    tables_in_job: set[str],
) -> dict[str, Any]:
    homogeneous = is_homogeneous(path)
    columns_report = _compare_columns(source, target, homogeneous)
    existence, existence_blocker = _existence(target, create_if_missing)
    if not target.exists and create_if_missing:
        columns_report["missing_on_target"] = []
        columns_report["type_mismatches"] = []
        columns_report["nullability_mismatches"] = []

    constraints = []
    for c in target.constraints:
        if c.kind == "primary_key":
            constraints.append(_constraint_entry(c, default_action="keep"))
        elif c.kind in {"check", "unique"}:
            constraints.append(
                _constraint_entry(
                    c,
                    default_action="disable",
                    reason="Disable check/unique constraints during bulk load, then restore",
                    severity="warning",
                )
            )

    indexes = []
    for idx in target.indexes:
        is_pk = bool(idx.extra.get("is_primary_key"))
        indexes.append(
            _constraint_entry(
                idx,
                kind="secondary" if not is_pk else "primary",
                default_action="keep" if is_pk else "disable",
                reason=None if is_pk else "Secondary index slows bulk load",
                severity="info" if is_pk else "warning",
            )
        )

    foreign_keys = []
    for fk in target.foreign_keys:
        referenced = str(fk.extra.get("referenced") or fk.extra.get("referenced_table") or "")
        in_job = referenced.lower() in {t.lower() for t in tables_in_job}
        foreign_keys.append(
            {
                "id": fk.object_id,
                "kind": "foreign_key",
                "direction": fk.extra.get("direction", "outgoing"),
                "referenced": referenced,
                "referenced_in_job": in_job,
                "severity": "warning",
                "recommended_action": "disable",
                "reason": "Disable foreign keys during bulk load, then restore",
                **({"definition": fk.extra["definition"]} if fk.extra.get("definition") else {}),
            }
        )

    triggers = [
        {
            "id": tg.object_id,
            "kind": "trigger",
            "timing": tg.extra.get("timing", "unknown"),
            "severity": "warning",
            "recommended_action": "disable",
            "reason": "INSERT triggers fire per row during bulk load",
            **({"definition": tg.extra["definition"]} if tg.extra.get("definition") else {}),
        }
        for tg in target.triggers
    ]

    identity_cols = [c for c in source.columns if c.is_identity] or [
        c for c in target.columns if c.is_identity
    ]
    identity = None
    if identity_cols:
        identity = {
            "has_identity_or_serial": True,
            "recommended_action": "set_insert_identity",
            "reason": "Preserve source keys on identity/serial columns",
        }

    blockers = existence_blocker
    if any(m["severity"] == "blocker" for m in columns_report["type_mismatches"]):
        blockers = True
    if any(c["severity"] == "blocker" for c in columns_report["missing_on_target"]):
        blockers = True

    return {
        "source": {"schema": source.schema, "table": source.table},
        "target": {"schema": target.schema, "table": target.table},
        "existence": existence,
        "row_count_source": source.row_count,
        "row_count_target": target.row_count,
        "columns": columns_report,
        "constraints": constraints,
        "indexes": indexes,
        "foreign_keys": foreign_keys,
        "triggers": triggers,
        "identity": identity,
        "has_blocker": blockers,
        "warning_count": _count_severity("warning", columns_report, constraints, indexes, foreign_keys, triggers),
    }


def summarize_preflight(tables: list[dict[str, Any]], extra_blockers: int = 0) -> dict[str, Any]:
    blockers = extra_blockers + sum(1 for t in tables if t.get("has_blocker"))
    warnings = sum(int(t.get("warning_count") or 0) for t in tables)
    ok = sum(1 for t in tables if not t.get("has_blocker") and not t.get("warning_count"))
    return {
        "blockers": blockers,
        "warnings": warnings,
        "ok": ok,
        "can_start": blockers == 0,
    }


def _existence(target: TableInventory, create_if_missing: bool) -> tuple[str, bool]:
    if target.exists:
        return "exists", False
    if create_if_missing:
        return "missing", False
    return "missing", True


def _compare_columns(
    source: TableInventory,
    target: TableInventory,
    homogeneous: bool,
) -> dict[str, Any]:
    src_by = {c.name.lower(): c for c in source.columns}
    tgt_by = {c.name.lower(): c for c in target.columns}
    matched: list[dict[str, str]] = []
    missing_on_target: list[dict[str, Any]] = []
    extra_on_target: list[dict[str, str]] = []
    type_mismatches: list[dict[str, Any]] = []
    nullability_mismatches: list[dict[str, Any]] = []

    for key, col in src_by.items():
        tgt = tgt_by.get(key)
        if tgt is None:
            missing_on_target.append({
                "name": col.name,
                "source_type": col.type_name,
                "severity": "blocker",
                "message": f"Column {col.name} is missing on the target table",
            })
            continue
        src_n = normalize_type(col.type_name)
        tgt_n = normalize_type(tgt.type_name)
        if src_n == tgt_n:
            matched.append({
                "name": col.name,
                "source_type": col.type_name,
                "target_type": tgt.type_name,
            })
        else:
            severity: Severity = "blocker" if homogeneous else "warning"
            message = (
                "Not assignment-compatible"
                if homogeneous
                else "Heterogeneous type mapping is not applied yet — review before load"
            )
            type_mismatches.append({
                "name": col.name,
                "source_type": col.type_name,
                "target_type": tgt.type_name,
                "severity": severity,
                "message": message,
            })
        if col.nullable and not tgt.nullable:
            nullability_mismatches.append({
                "name": col.name,
                "severity": "warning",
                "message": "Source allows NULL but target does not",
            })

    for key, col in tgt_by.items():
        if key not in src_by:
            extra_on_target.append({"name": col.name, "target_type": col.type_name})

    return {
        "matched": matched,
        "missing_on_target": missing_on_target,
        "extra_on_target": extra_on_target,
        "type_mismatches": type_mismatches,
        "nullability_mismatches": nullability_mismatches,
    }


def _constraint_entry(
    obj: ObjectInventory,
    *,
    default_action: str,
    reason: str | None = None,
    severity: Severity = "info",
    kind: str | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": obj.object_id,
        "kind": kind or obj.kind,
        "severity": severity,
        "recommended_action": default_action,
        "reason": reason,
        **({k: v for k, v in obj.extra.items() if k in {"referenced", "direction", "definition"}}),
    }
    return out


def _count_severity(level: str, *groups: Any) -> int:
    total = 0
    for group in groups:
        if isinstance(group, dict):
            for value in group.values():
                if isinstance(value, list):
                    total += sum(1 for item in value if isinstance(item, dict) and item.get("severity") == level)
        elif isinstance(group, list):
            total += sum(1 for item in group if isinstance(item, dict) and item.get("severity") == level)
    return total
