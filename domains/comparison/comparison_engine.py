"""
Module: comparison_engine.py
Purpose: Schema comparison utilities
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from collections import defaultdict

from domains.comparison.constraint_comparator import ConstraintComparator
from domains.comparison.index_comparator import (
    IndexComparator,
    _index_is_pk,
    _index_key_columns,
    _index_name,
)
from domains.comparison.object_comparator import DiffEntry, ObjectComparator, significant_diffs
from domains.discovery.discovery_engine import DiscoveryResult
from shared.kernel.database_object import DatabaseObject, Table


class MatchStatus(StrEnum):
    EXACT = "exact"
    PARTIAL = "partial"
    SOURCE_ONLY = "source_only"
    TARGET_ONLY = "target_only"


@dataclass
class ObjectMatch:
    source_object: DatabaseObject | None
    target_object: DatabaseObject | None
    match_status: MatchStatus
    differences: list[DiffEntry]


@dataclass
class ComparisonTreeNode:
    name: str
    node_type: str
    status: MatchStatus
    children: list[ComparisonTreeNode] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class ComparisonResult:
    source_database: str
    target_database: str
    total_source_objects: int
    total_target_objects: int
    matched: int
    source_only: int
    target_only: int
    partial_match: int
    tree: list[ComparisonTreeNode]
    source_tree: list[ComparisonTreeNode]
    target_tree: list[ComparisonTreeNode]
    duration_ms: float


_WORST_ORDER = {
    MatchStatus.EXACT: 0,
    MatchStatus.PARTIAL: 1,
    MatchStatus.SOURCE_ONLY: 2,
    MatchStatus.TARGET_ONLY: 2,
}

_OBJECT_CATEGORY_ORDER = {
    "table": 0,
    "procedure": 1,
    "function": 2,
    "view": 3,
}

_OBJECT_CATEGORY_LABELS = {
    "table": "Tables",
    "procedure": "Stored Procedures",
    "function": "Functions",
    "view": "Views",
}


def _worse_status(a: MatchStatus, b: MatchStatus) -> MatchStatus:
    return a if _WORST_ORDER.get(a, 0) >= _WORST_ORDER.get(b, 0) else b


def _objects_in_schema(bucket: dict[str, list], schema: str) -> list:
    """Collect objects from discovery buckets keyed as ``database.schema``."""
    if not schema:
        return [obj for objs in bucket.values() for obj in objs]
    suffix = f".{schema}"
    out: list = []
    for key, objs in bucket.items():
        if key.endswith(suffix) or key.split(".")[-1] == schema:
            out.extend(objs)
    return out


class ComparisonEngine:

    def __init__(
        self,
        comparator: ObjectComparator | None = None,
        index_comparator: IndexComparator | None = None,
        constraint_comparator: ConstraintComparator | None = None,
    ):
        self._comparator = comparator or ObjectComparator()
        # Fix 4.5: index and constraint comparators for full schema parity
        self._index_comparator = index_comparator or IndexComparator()
        self._constraint_comparator = constraint_comparator or ConstraintComparator()

    def compare_databases(
        self,
        source_objects: DiscoveryResult,
        target_objects: DiscoveryResult,
        *,
        source_schema: str | None = None,
        target_schema: str | None = None,
        source_database: str | None = None,
        target_database: str | None = None,
    ) -> ComparisonResult:
        start = time.perf_counter()

        source_db = source_database or self._extract_database_name(source_objects)
        target_db = target_database or self._extract_database_name(target_objects)

        cross_schema = (
            source_schema is not None
            and target_schema is not None
            and source_schema != target_schema
        )
        schema_kwargs = (
            {"source_schema": source_schema, "target_schema": target_schema}
            if cross_schema
            else {}
        )

        all_matches: list[ObjectMatch] = []

        table_matches = self.compare_tables(
            source_objects.tables,
            target_objects.tables,
            **schema_kwargs,
        )
        all_matches.extend(table_matches)

        proc_matches = self.compare_procedures(
            source_objects.procedures,
            target_objects.procedures,
            **schema_kwargs,
        )
        all_matches.extend(proc_matches)

        func_matches = self.compare_functions(
            source_objects.functions,
            target_objects.functions,
            **schema_kwargs,
        )
        all_matches.extend(func_matches)

        tree = self._build_comparison_tree(
            source_objects,
            target_objects,
            all_matches,
            source_schema=source_schema if cross_schema else None,
            target_schema=target_schema if cross_schema else None,
            source_database=source_db,
            target_database=target_db,
        )

        effective_source_schema = source_schema or self._first_schema(source_objects)
        effective_target_schema = target_schema or self._first_schema(target_objects)
        source_tree = self._build_inventory_tree(
            source_objects,
            database=source_db,
            schema=effective_source_schema,
        )
        target_tree = self._build_inventory_tree(
            target_objects,
            database=target_db,
            schema=effective_target_schema,
        )

        matched = sum(1 for m in all_matches if m.match_status == MatchStatus.EXACT)
        source_only = sum(1 for m in all_matches if m.match_status == MatchStatus.SOURCE_ONLY)
        target_only = sum(1 for m in all_matches if m.match_status == MatchStatus.TARGET_ONLY)
        partial_match = sum(1 for m in all_matches if m.match_status == MatchStatus.PARTIAL)

        duration = (time.perf_counter() - start) * 1000

        return ComparisonResult(
            source_database=source_db,
            target_database=target_db,
            total_source_objects=source_objects.total_objects,
            total_target_objects=target_objects.total_objects,
            matched=matched,
            source_only=source_only,
            target_only=target_only,
            partial_match=partial_match,
            tree=tree,
            source_tree=source_tree,
            target_tree=target_tree,
            duration_ms=duration,
        )

    def _first_schema(self, result: DiscoveryResult) -> str:
        for bucket in (result.tables, result.procedures, result.functions, result.views):
            for key in bucket:
                if "." in key:
                    return key.split(".")[-1]
                return key
        return "dbo"

    def _format_column_type(self, data_type: Any) -> str:
        name = data_type.type_name
        max_length = getattr(data_type, "max_length", None)
        precision = getattr(data_type, "precision", None)
        scale = getattr(data_type, "scale", None)
        if max_length:
            return f"{name}({max_length})"
        if precision is not None:
            return f"{name}({precision},{scale or 0})"
        return name

    def _build_inventory_tree(
        self,
        discovery: DiscoveryResult,
        *,
        database: str,
        schema: str,
    ) -> list[ComparisonTreeNode]:
        """Build a side-specific inventory tree (objects that exist on one server only)."""
        tables = _objects_in_schema(discovery.tables, schema)
        procedures = _objects_in_schema(discovery.procedures, schema)
        functions = _objects_in_schema(discovery.functions, schema)

        if not tables and not procedures and not functions:
            return []

        db_node = ComparisonTreeNode(
            name=database,
            node_type="database",
            status=MatchStatus.EXACT,
            properties={"database": database},
        )
        schema_node = ComparisonTreeNode(
            name=schema,
            node_type="schema",
            status=MatchStatus.EXACT,
            properties={"schema": schema},
        )
        db_node.children.append(schema_node)

        if tables:
            tables_node = self._category_node("table")
            for table in sorted(tables, key=lambda t: t.object_name.lower()):
                tables_node.children.append(self._inventory_table_node(table))
            schema_node.children.append(tables_node)
        if procedures:
            procs_node = self._category_node("procedure")
            for proc in sorted(procedures, key=lambda p: p.object_name.lower()):
                procs_node.children.append(self._inventory_object_node(proc, "procedure"))
            schema_node.children.append(procs_node)
        if functions:
            funcs_node = self._category_node("function")
            for func in sorted(functions, key=lambda p: p.object_name.lower()):
                funcs_node.children.append(self._inventory_object_node(func, "function"))
            schema_node.children.append(funcs_node)

        return [db_node]

    def _category_node(self, object_type: str) -> ComparisonTreeNode:
        return ComparisonTreeNode(
            name=_OBJECT_CATEGORY_LABELS.get(object_type, object_type.title()),
            node_type="category",
            status=MatchStatus.EXACT,
            properties={"object_category": object_type},
        )

    def _inventory_table_node(self, table: Table) -> ComparisonTreeNode:
        node = ComparisonTreeNode(
            name=table.object_name,
            node_type="table",
            status=MatchStatus.EXACT,
        )
        for col in sorted(table.columns, key=lambda c: c.ordinal_position):
            node.children.append(
                ComparisonTreeNode(
                    name=col.column_name,
                    node_type="column",
                    status=MatchStatus.EXACT,
                    properties={
                        "data_type": self._format_column_type(col.data_type),
                        "nullable": col.is_nullable,
                    },
                )
            )
        indexes = table.properties.get("indexes", [])
        node.children.extend(self._index_inventory_children(indexes))
        return node

    def _index_inventory_children(self, indexes: list) -> list[ComparisonTreeNode]:
        children: list[ComparisonTreeNode] = []
        for idx in sorted(indexes, key=lambda i: _index_name(i).lower()):
            if _index_is_pk(idx):
                continue
            props = getattr(idx, "properties", {}) or {}
            children.append(
                ComparisonTreeNode(
                    name=_index_name(idx),
                    node_type="index",
                    status=MatchStatus.EXACT,
                    properties={
                        "is_unique": props.get("is_unique", False),
                        "key_columns": _index_key_columns(idx),
                    },
                )
            )
        return children

    def _inventory_object_node(
        self, obj: DatabaseObject, node_type: str,
    ) -> ComparisonTreeNode:
        return ComparisonTreeNode(
            name=obj.object_name,
            node_type=node_type,
            status=MatchStatus.EXACT,
        )

    def _extract_database_name(self, result: DiscoveryResult) -> str:
        if result.databases:
            return result.databases[0].database_name
        for bucket in (result.tables, result.procedures, result.functions, result.views):
            for objs in bucket.values():
                if objs:
                    return objs[0].database_name
        return "unknown"

    def compare_tables(
        self,
        source_tables: dict[str, list[Table]],
        target_tables: dict[str, list[Table]],
        *,
        source_schema: str | None = None,
        target_schema: str | None = None,
    ) -> list[ObjectMatch]:
        if source_schema is not None and target_schema is not None:
            return self._match_objects_by_name(
                _objects_in_schema(source_tables, source_schema),
                _objects_in_schema(target_tables, target_schema),
                compare_fn=self._compare_table_columns,
            )

        matches: list[ObjectMatch] = []
        all_keys = set(source_tables.keys()) | set(target_tables.keys())

        for key in all_keys:
            matches.extend(
                self._match_objects_by_name(
                    source_tables.get(key, []),
                    target_tables.get(key, []),
                    compare_fn=self._compare_table_columns,
                )
            )

        return matches

    def _match_objects_by_name(
        self,
        src_list: list,
        tgt_list: list,
        *,
        compare_fn,
        kind: str = "table",
    ) -> list[ObjectMatch]:
        matches: list[ObjectMatch] = []
        src_by_name = {o.object_name.lower(): o for o in src_list}
        tgt_by_name = {o.object_name.lower(): o for o in tgt_list}
        all_names = set(src_by_name.keys()) | set(tgt_by_name.keys())

        for name in sorted(all_names):
            src = src_by_name.get(name)
            tgt = tgt_by_name.get(name)

            if src and not tgt:
                matches.append(ObjectMatch(
                    source_object=src,
                    target_object=None,
                    match_status=MatchStatus.SOURCE_ONLY,
                    differences=[],
                ))
            elif tgt and not src:
                matches.append(ObjectMatch(
                    source_object=None,
                    target_object=tgt,
                    match_status=MatchStatus.TARGET_ONLY,
                    differences=[],
                ))
            else:
                if kind == "procedure":
                    diffs = self._comparator.compare_procedure_signatures(src, tgt)
                elif kind == "function":
                    diffs = self._comparator.compare_function_signatures(src, tgt)
                else:
                    diffs = compare_fn(src, tgt)
                status = (
                    MatchStatus.EXACT
                    if not significant_diffs(diffs)
                    else MatchStatus.PARTIAL
                )
                matches.append(ObjectMatch(
                    source_object=src,
                    target_object=tgt,
                    match_status=status,
                    differences=diffs,
                ))

        return matches

    def _compare_table_columns(self, source: Table, target: Table) -> list[DiffEntry]:
        # Fix 4.5: compare columns + indexes + constraints
        diffs = self._comparator.compare_columns(source.columns, target.columns)
        # Check both direct attributes (IndexInfo) and properties dict (DatabaseObject)
        src_indexes = getattr(source, "indexes", None) or source.properties.get("indexes", [])
        tgt_indexes = getattr(target, "indexes", None) or target.properties.get("indexes", [])
        if src_indexes or tgt_indexes:
            diffs += self._index_comparator.compare(src_indexes, tgt_indexes)
        src_constraints = getattr(source, "constraints", None) or source.properties.get("constraints", [])
        tgt_constraints = getattr(target, "constraints", None) or target.properties.get("constraints", [])
        if src_constraints or tgt_constraints:
            diffs += self._constraint_comparator.compare(src_constraints, tgt_constraints)
        return diffs

    def compare_procedures(
        self,
        source_procs: dict[str, list[DatabaseObject]],
        target_procs: dict[str, list[DatabaseObject]],
        *,
        source_schema: str | None = None,
        target_schema: str | None = None,
    ) -> list[ObjectMatch]:
        return self._compare_object_lists(
            source_procs,
            target_procs,
            "procedure",
            source_schema=source_schema,
            target_schema=target_schema,
        )

    def compare_functions(
        self,
        source_funcs: dict[str, list[DatabaseObject]],
        target_funcs: dict[str, list[DatabaseObject]],
        *,
        source_schema: str | None = None,
        target_schema: str | None = None,
    ) -> list[ObjectMatch]:
        return self._compare_object_lists(
            source_funcs,
            target_funcs,
            "function",
            source_schema=source_schema,
            target_schema=target_schema,
        )

    def _compare_object_lists(
        self,
        source_dict: dict[str, list[DatabaseObject]],
        target_dict: dict[str, list[DatabaseObject]],
        kind: str,
        *,
        source_schema: str | None = None,
        target_schema: str | None = None,
    ) -> list[ObjectMatch]:
        if source_schema is not None and target_schema is not None:
            return self._match_objects_by_name(
                _objects_in_schema(source_dict, source_schema),
                _objects_in_schema(target_dict, target_schema),
                compare_fn=None,
                kind=kind,
            )

        matches: list[ObjectMatch] = []
        all_keys = set(source_dict.keys()) | set(target_dict.keys())

        for key in all_keys:
            matches.extend(
                self._match_objects_by_name(
                    source_dict.get(key, []),
                    target_dict.get(key, []),
                    compare_fn=None,
                    kind=kind,
                )
            )

        return matches

    def _build_comparison_tree(
        self,
        source: DiscoveryResult,
        target: DiscoveryResult,
        all_matches: list[ObjectMatch],
        *,
        source_schema: str | None = None,
        target_schema: str | None = None,
        source_database: str | None = None,
        target_database: str | None = None,
    ) -> list[ComparisonTreeNode]:
        cross_schema = source_schema is not None and target_schema is not None

        if cross_schema:
            source_db = source_database or self._extract_database_name(source)
            target_db = target_database or self._extract_database_name(target)
            db_node = ComparisonTreeNode(
                name=source_db,
                node_type="database",
                status=MatchStatus.EXACT,
                properties={
                    "source_database": source_db,
                    "target_database": target_db,
                },
            )
            schema_node = ComparisonTreeNode(
                name=source_schema,
                node_type="schema",
                status=MatchStatus.EXACT,
                properties={
                    "source_schema": source_schema,
                    "target_schema": target_schema,
                },
            )
            db_node.children.append(schema_node)

            self._append_grouped_matches(schema_node, all_matches)

            self._propagate_status(db_node)
            return [db_node]

        db_nodes: dict[str, ComparisonTreeNode] = {}

        for match in all_matches:
            obj = match.source_object or match.target_object
            db_name = obj.database_name if obj else "unknown"
            schema_name = obj.schema_name if obj else "unknown"

            if db_name not in db_nodes:
                db_nodes[db_name] = ComparisonTreeNode(
                    name=db_name, node_type="database", status=MatchStatus.EXACT,
                )

            db_node = db_nodes[db_name]
            schema_node = self._find_or_create_child(db_node, schema_name, "schema")
            if not schema_node.properties.get("_grouped"):
                self._append_grouped_matches(schema_node, [
                    m for m in all_matches
                    if (m.source_object or m.target_object)
                    and (m.source_object or m.target_object).schema_name == schema_name
                ])
                schema_node.properties["_grouped"] = True

        for db_node in db_nodes.values():
            self._propagate_status(db_node)

        return list(db_nodes.values())

    def _append_grouped_matches(
        self,
        schema_node: ComparisonTreeNode,
        matches: list[ObjectMatch],
    ) -> None:
        by_type: dict[str, list[ObjectMatch]] = defaultdict(list)
        for match in matches:
            obj = match.source_object or match.target_object
            if not obj:
                continue
            by_type[obj.object_type.value].append(match)

        for obj_type in sorted(
            by_type.keys(),
            key=lambda t: _OBJECT_CATEGORY_ORDER.get(t, 99),
        ):
            category_node = self._category_node(obj_type)
            for match in sorted(
                by_type[obj_type],
                key=lambda m: (m.source_object or m.target_object).object_name.lower(),
            ):
                obj = match.source_object or match.target_object
                category_node.children.append(
                    self._object_tree_node(obj, obj_type, match)
                )
            self._propagate_status(category_node)
            schema_node.children.append(category_node)

    def _object_tree_node(
        self,
        obj: DatabaseObject | Table,
        obj_type_str: str,
        match: ObjectMatch,
    ) -> ComparisonTreeNode:
        obj_node = ComparisonTreeNode(
            name=obj.object_name if obj else "unknown",
            node_type=obj_type_str,
            status=match.match_status,
            properties={
                "differences": [
                    {
                        "property": d.property_name,
                        "source": d.source_value,
                        "target": d.target_value,
                        "severity": d.severity,
                    }
                    for d in match.differences
                ],
            },
        )

        src_table = match.source_object if isinstance(match.source_object, Table) else None
        tgt_table = match.target_object if isinstance(match.target_object, Table) else None
        if src_table or tgt_table:
            obj_node.children.extend(
                self._column_diff_children(src_table, tgt_table, match.differences)
            )
            obj_node.children.extend(
                self._index_diff_children(src_table, tgt_table, match.differences)
            )

        if match.differences:
            for diff in match.differences:
                parts = diff.property_name.split(".")
                if len(parts) >= 2 and parts[0] == "constraint":
                    child_name = parts[1]
                    obj_node.children.append(
                        ComparisonTreeNode(
                            name=child_name,
                            node_type="constraint",
                            status=MatchStatus.PARTIAL,
                            properties={
                                "diff": {
                                    "property": diff.property_name,
                                    "source": diff.source_value,
                                    "target": diff.target_value,
                                    "severity": diff.severity,
                                },
                            },
                        )
                    )

        return obj_node

    def _index_diff_children(
        self,
        source: Table | None,
        target: Table | None,
        differences: list[DiffEntry],
    ) -> list[ComparisonTreeNode]:
        src_indexes = (source.properties.get("indexes", []) if source else [])
        tgt_indexes = (target.properties.get("indexes", []) if target else [])
        src_map = {
            _index_name(idx).lower(): idx
            for idx in src_indexes
            if not _index_is_pk(idx)
        }
        tgt_map = {
            _index_name(idx).lower(): idx
            for idx in tgt_indexes
            if not _index_is_pk(idx)
        }
        diff_by_index: dict[str, list[DiffEntry]] = {}
        for diff in significant_diffs(differences):
            parts = diff.property_name.split(".")
            if parts[0] == "index" and len(parts) >= 2:
                diff_by_index.setdefault(parts[1].lower(), []).append(diff)

        all_names = sorted(set(src_map) | set(tgt_map))
        children: list[ComparisonTreeNode] = []
        for name in all_names:
            src_idx = src_map.get(name)
            tgt_idx = tgt_map.get(name)
            if src_idx and not tgt_idx:
                status = MatchStatus.SOURCE_ONLY
            elif tgt_idx and not src_idx:
                status = MatchStatus.TARGET_ONLY
            elif diff_by_index.get(name):
                status = MatchStatus.PARTIAL
            else:
                status = MatchStatus.EXACT
            children.append(
                ComparisonTreeNode(
                    name=_index_name(src_idx or tgt_idx),
                    node_type="index",
                    status=status,
                    properties={
                        "source_columns": _index_key_columns(src_idx) if src_idx else None,
                        "target_columns": _index_key_columns(tgt_idx) if tgt_idx else None,
                    },
                )
            )
        return children

    def _column_diff_children(
        self,
        source: Table | None,
        target: Table | None,
        differences: list[DiffEntry],
    ) -> list[ComparisonTreeNode]:
        """Emit one tree child per column with source/target data types."""
        src_by_name = {c.column_name: c for c in (source.columns if source else [])}
        tgt_by_name = {c.column_name: c for c in (target.columns if target else [])}
        diff_by_col: dict[str, list[DiffEntry]] = {}
        for diff in significant_diffs(differences):
            parts = diff.property_name.split(".")
            if parts[0] == "column" and len(parts) >= 2:
                col_name = parts[1]
                diff_by_col.setdefault(col_name, []).append(diff)

        all_names = sorted(set(src_by_name) | set(tgt_by_name))
        children: list[ComparisonTreeNode] = []
        for name in all_names:
            sc = src_by_name.get(name)
            tc = tgt_by_name.get(name)
            src_type = self._format_column_type(sc.data_type) if sc else None
            tgt_type = self._format_column_type(tc.data_type) if tc else None
            if sc and not tc:
                status = MatchStatus.SOURCE_ONLY
            elif tc and not sc:
                status = MatchStatus.TARGET_ONLY
            elif diff_by_col.get(name):
                status = MatchStatus.PARTIAL
            else:
                status = MatchStatus.EXACT
            children.append(
                ComparisonTreeNode(
                    name=name,
                    node_type="column",
                    status=status,
                    properties={
                        "source_type": src_type,
                        "target_type": tgt_type,
                    },
                )
            )
        return children

    def _find_or_create_child(
        self, parent: ComparisonTreeNode, name: str, node_type: str,
    ) -> ComparisonTreeNode:
        for child in parent.children:
            if child.name == name and child.node_type == node_type:
                return child
        node = ComparisonTreeNode(name=name, node_type=node_type, status=MatchStatus.EXACT)
        parent.children.append(node)
        return node

    def _propagate_status(self, node: ComparisonTreeNode) -> MatchStatus:
        if not node.children:
            return node.status

        worst = MatchStatus.EXACT
        for child in node.children:
            child_status = self._propagate_status(child)
            worst = _worse_status(worst, child_status)

        node.status = worst
        return worst
