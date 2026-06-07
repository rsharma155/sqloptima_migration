"""
Module: domains/comparison/constraint_comparator.py
Purpose: Compares constraint definitions (FKs, unique constraints, check constraints)
         between source and target databases.
         Accepts either ConstraintInfo dataclass or DatabaseObject instances.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from domains.comparison.object_comparator import DiffEntry


class ConstraintType(StrEnum):
    FOREIGN_KEY = "FOREIGN_KEY"
    UNIQUE = "UNIQUE"
    CHECK = "CHECK"
    DEFAULT = "DEFAULT"


@dataclass
class ConstraintInfo:
    name: str
    constraint_type: ConstraintType
    columns: list[str] = field(default_factory=list)
    referenced_table: str | None = None
    referenced_columns: list[str] = field(default_factory=list)
    check_clause: str | None = None


def _constraint_name(obj: Any) -> str:
    return getattr(obj, "name", None) or getattr(obj, "object_name", "")


def _constraint_type(obj: Any) -> str:
    ct = getattr(obj, "constraint_type", None)
    if ct is not None:
        return str(ct)
    props = getattr(obj, "properties", {}) or {}
    return str(props.get("constraint_type", "UNKNOWN"))


def _is_fk(obj: Any) -> bool:
    return _constraint_type(obj) in ("FOREIGN_KEY", str(ConstraintType.FOREIGN_KEY))


class ConstraintComparator:
    """Compares constraint lists between source and target schemas.

    Accepts both ConstraintInfo dataclasses and DatabaseObject instances.
    """

    def compare(
        self,
        source_constraints: list[Any],
        target_constraints: list[Any],
    ) -> list[DiffEntry]:
        diffs: list[DiffEntry] = []

        src_map = {_constraint_name(c).lower(): c for c in source_constraints}
        tgt_map = {_constraint_name(c).lower(): c for c in target_constraints}

        for name, src_c in src_map.items():
            if name not in tgt_map:
                severity = "error" if _is_fk(src_c) else "error"
                diffs.append(DiffEntry(
                    property_name=f"constraint.{_constraint_name(src_c)}",
                    source_value="exists",
                    target_value="<missing>",
                    severity=severity,
                ))
            else:
                tgt_c = tgt_map[name]
                src_type = _constraint_type(src_c)
                tgt_type = _constraint_type(tgt_c)
                if src_type != tgt_type:
                    diffs.append(DiffEntry(
                        property_name=f"constraint.{_constraint_name(src_c)}.type",
                        source_value=src_type,
                        target_value=tgt_type,
                        severity="error",
                    ))

        for name, tgt_c in tgt_map.items():
            if name not in src_map:
                diffs.append(DiffEntry(
                    property_name=f"constraint.{_constraint_name(tgt_c)}",
                    source_value="<missing>",
                    target_value="exists",
                    severity="info",
                ))

        return diffs
