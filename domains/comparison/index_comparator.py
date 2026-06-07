"""
Module: domains/comparison/index_comparator.py
Purpose: Compares index definitions between source and target databases.
         Detects missing indexes that would cause query degradation after migration.
         Accepts either IndexInfo dataclass or DatabaseObject instances.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from domains.comparison.object_comparator import DiffEntry


@dataclass
class IndexInfo:
    name: str
    is_unique: bool = False
    is_primary_key: bool = False
    key_columns: list[str] = field(default_factory=list)
    include_columns: list[str] = field(default_factory=list)


def _index_name(obj: Any) -> str:
    """Return the index name regardless of whether obj is IndexInfo or DatabaseObject."""
    return getattr(obj, "name", None) or getattr(obj, "object_name", "")


def _index_is_pk(obj: Any) -> bool:
    pk = getattr(obj, "is_primary_key", None)
    if pk is not None:
        return bool(pk)
    props = getattr(obj, "properties", {}) or {}
    return bool(props.get("is_primary_key", False))


def _index_is_unique(obj: Any) -> bool:
    u = getattr(obj, "is_unique", None)
    if u is not None:
        return bool(u)
    props = getattr(obj, "properties", {}) or {}
    return bool(props.get("is_unique", False))


def _index_key_columns(obj: Any) -> list[str]:
    cols = getattr(obj, "key_columns", None)
    if cols is not None:
        return cols
    props = getattr(obj, "properties", {}) or {}
    raw = props.get("columns", [])
    if isinstance(raw, str):
        return [c.strip() for c in raw.split(",") if c.strip()]
    return list(raw)


class IndexComparator:
    """Compares index lists between source (SQL Server) and target (PostgreSQL).

    Primary keys are excluded — they are handled by the column comparator.
    Comparison is name-normalised to lowercase.
    Accepts both IndexInfo dataclasses and DatabaseObject instances.
    """

    def compare(
        self,
        source_indexes: list[Any],
        target_indexes: list[Any],
    ) -> list[DiffEntry]:
        diffs: list[DiffEntry] = []

        src_map = {_index_name(idx).lower(): idx for idx in source_indexes if not _index_is_pk(idx)}
        tgt_map = {_index_name(idx).lower(): idx for idx in target_indexes if not _index_is_pk(idx)}

        for name, src_idx in src_map.items():
            if name not in tgt_map:
                diffs.append(DiffEntry(
                    property_name=f"index.{_index_name(src_idx)}",
                    source_value="exists",
                    target_value="<missing>",
                    severity="error",
                ))
            else:
                tgt_idx = tgt_map[name]
                src_cols = [c.lower() for c in _index_key_columns(src_idx)]
                tgt_cols = [c.lower() for c in _index_key_columns(tgt_idx)]
                if src_cols and tgt_cols and src_cols != tgt_cols:
                    diffs.append(DiffEntry(
                        property_name=f"index.{_index_name(src_idx)}.key_columns",
                        source_value=_index_key_columns(src_idx),
                        target_value=_index_key_columns(tgt_idx),
                        severity="warning",
                    ))
                if _index_is_unique(src_idx) and not _index_is_unique(tgt_idx):
                    diffs.append(DiffEntry(
                        property_name=f"index.{_index_name(src_idx)}.is_unique",
                        source_value=True,
                        target_value=False,
                        severity="error",
                    ))

        for name, tgt_idx in tgt_map.items():
            if name not in src_map:
                diffs.append(DiffEntry(
                    property_name=f"index.{_index_name(tgt_idx)}",
                    source_value="<missing>",
                    target_value="exists",
                    severity="info",
                ))

        return diffs
