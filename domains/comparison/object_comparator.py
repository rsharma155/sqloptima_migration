"""
Module: object_comparator.py
Purpose: Schema comparison utilities
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from typing import Any

from domains.transpilation.type_mappings import get_type_mapping
from shared.kernel.database_object import Column, DatabaseObject, DataType

# PostgreSQL information_schema names → canonical names used in type mappings.
_PG_TO_CANONICAL: dict[str, str] = {
    "integer": "INTEGER",
    "bigint": "BIGINT",
    "smallint": "SMALLINT",
    "boolean": "BOOLEAN",
    "numeric": "NUMERIC",
    "decimal": "NUMERIC",
    "real": "REAL",
    "double precision": "DOUBLE PRECISION",
    "character varying": "VARCHAR",
    "varchar": "VARCHAR",
    "character": "CHAR",
    "char": "CHAR",
    "text": "TEXT",
    "bytea": "BYTEA",
    "uuid": "UUID",
    "timestamp without time zone": "TIMESTAMP",
    "timestamp with time zone": "TIMESTAMPTZ",
    "timestamptz": "TIMESTAMPTZ",
    "date": "DATE",
    "time without time zone": "TIME",
    "jsonb": "JSONB",
    "json": "JSONB",
    "xml": "XML",
}


def _canonical_pg_type(type_name: str) -> str:
    return _PG_TO_CANONICAL.get(type_name.lower().strip(), type_name.upper().replace(" ", ""))


class DiffEntry:
    def __init__(
        self, property_name: str, source_value: Any, target_value: Any,
        severity: str = "warning",
    ):
        self.property_name = property_name
        self.source_value = source_value
        self.target_value = target_value
        self.severity = severity


def significant_diffs(diffs: list[DiffEntry]) -> list[DiffEntry]:
    """Diffs that should affect EXACT vs PARTIAL (ignore info-level noise like defaults)."""
    return [d for d in diffs if d.severity in ("error", "warning")]


class ObjectComparator:

    def compare_columns(
        self, source_columns: list[Column], target_columns: list[Column],
    ) -> list[DiffEntry]:
        diffs: list[DiffEntry] = []
        source_by_name = {c.column_name: c for c in source_columns}
        target_by_name = {c.column_name: c for c in target_columns}
        all_names = set(source_by_name.keys()) | set(target_by_name.keys())

        for name in sorted(all_names):
            sc = source_by_name.get(name)
            tc = target_by_name.get(name)

            if sc and not tc:
                diffs.append(DiffEntry(
                    property_name=f"column.{name}",
                    source_value="exists",
                    target_value="<missing>",
                    severity="error",
                ))
            elif tc and not sc:
                diffs.append(DiffEntry(
                    property_name=f"column.{name}",
                    source_value="<missing>",
                    target_value="exists",
                    severity="error",
                ))
            else:
                diffs.extend(self._compare_column(sc, tc))

        return diffs

    def _compare_column(self, source: Column, target: Column) -> list[DiffEntry]:
        diffs: list[DiffEntry] = []

        type_diff = self.compare_column_types(
            source.data_type, target.data_type, column_name=source.column_name,
        )
        if type_diff:
            diffs.append(type_diff)

        if source.is_nullable != target.is_nullable:
            diffs.append(DiffEntry(
                property_name=f"column.{source.column_name}.nullable",
                source_value=source.is_nullable,
                target_value=target.is_nullable,
                severity="warning",
            ))

        if source.default_value != target.default_value:
            diffs.append(DiffEntry(
                property_name=f"column.{source.column_name}.default",
                source_value=source.default_value,
                target_value=target.default_value,
                severity="info",
            ))

        return diffs

    def compare_column_types(
        self,
        source_type: DataType,
        target_type: DataType,
        *,
        column_name: str = "unknown",
    ) -> DiffEntry | None:
        mapping = get_type_mapping(source_type.type_name)
        expected = mapping.target_type.upper().replace(" ", "")
        # Target is PostgreSQL — normalize information_schema names (e.g. character varying).
        actual = _canonical_pg_type(target_type.type_name)

        if expected == actual:
            has_precision = source_type.precision is not None and target_type.precision is not None
            prec_diff = source_type.precision != target_type.precision
            scale_diff = source_type.scale != target_type.scale
            if has_precision and (prec_diff or scale_diff):
                return DiffEntry(
                    property_name=f"column.{column_name}.type",
                    source_value=f"{source_type.type_name}({source_type.precision},{source_type.scale})",
                    target_value=f"{target_type.type_name}({target_type.precision},{target_type.scale})",
                    severity="info",
                )
            return None

        return DiffEntry(
            property_name=f"column.{column_name}.type",
            source_value=source_type.type_name,
            target_value=target_type.type_name,
            severity="warning",
        )

    def compare_indexes(
        self, source_indexes: list[DatabaseObject], target_indexes: list[DatabaseObject]
    ) -> list[DiffEntry]:
        diffs: list[DiffEntry] = []
        source_by_name = {idx.object_name: idx for idx in source_indexes}
        target_by_name = {idx.object_name: idx for idx in target_indexes}
        all_names = set(source_by_name.keys()) | set(target_by_name.keys())

        for name in sorted(all_names):
            si = source_by_name.get(name)
            ti = target_by_name.get(name)

            if si and not ti:
                diffs.append(DiffEntry(
                    property_name=f"index.{name}",
                    source_value="exists",
                    target_value="<missing>",
                    severity="error",
                ))
            elif ti and not si:
                diffs.append(DiffEntry(
                    property_name=f"index.{name}",
                    source_value="<missing>",
                    target_value="exists",
                    severity="error",
                ))

        return diffs

    def compare_constraints(
        self, source_constraints: list[DatabaseObject], target_constraints: list[DatabaseObject]
    ) -> list[DiffEntry]:
        diffs: list[DiffEntry] = []
        source_by_name = {c.object_name: c for c in source_constraints}
        target_by_name = {c.object_name: c for c in target_constraints}
        all_names = set(source_by_name.keys()) | set(target_by_name.keys())

        for name in sorted(all_names):
            sc = source_by_name.get(name)
            tc = target_by_name.get(name)

            if sc and not tc:
                diffs.append(DiffEntry(
                    property_name=f"constraint.{name}",
                    source_value="exists",
                    target_value="<missing>",
                    severity="error",
                ))
            elif tc and not sc:
                diffs.append(DiffEntry(
                    property_name=f"constraint.{name}",
                    source_value="<missing>",
                    target_value="exists",
                    severity="error",
                ))

        return diffs

    def compare_procedure_signatures(
        self, source: DatabaseObject, target: DatabaseObject,
    ) -> list[DiffEntry]:
        diffs: list[DiffEntry] = []

        if source.source_definition != target.source_definition:
            diffs.append(DiffEntry(
                property_name="definition",
                source_value="<source definition>",
                target_value="<target definition>",
                severity="warning",
            ))

        source_params = source.properties.get("parameters", "")
        target_params = target.properties.get("parameters", "")
        if source_params and target_params and source_params != target_params:
            diffs.append(DiffEntry(
                property_name="parameters",
                source_value=source_params,
                target_value=target_params,
                severity="warning",
            ))

        return diffs

    def compare_function_signatures(
        self, source: DatabaseObject, target: DatabaseObject,
    ) -> list[DiffEntry]:
        return self.compare_procedure_signatures(source, target)
