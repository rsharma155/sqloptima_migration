"""
Module: dependency_graph_engine.py
Purpose: Dependency graph construction, topological sort, SCC detection using NetworkX
Author: Migration Platform Team
Created: 2026-05-22
Domain: Lineage
Dependencies: networkx
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from typing import Any
from uuid import UUID

import networkx as nx

from shared.kernel.database_object import DatabaseObject
from shared.kernel.dependency_graph import (
    CircularDependency,
    DependencyEdge,
    DependencyType,
    GraphMetadata,
)


class DependencyGraphEngine:
    """Builds and analyzes dependency graphs of database objects.

    Uses NetworkX Directed Graph for:
    - Dependency ordering via topological sort
    - Circular dependency detection via strongly connected components (SCC)
    - Migration ordering
    - Recompilation planning
    """

    def __init__(self):
        self._graph: nx.DiGraph = nx.DiGraph()
        self._object_map: dict[UUID, DatabaseObject] = {}

    def add_object(self, obj: DatabaseObject) -> None:
        """Add a database object as a node in the graph."""
        self._object_map[obj.id] = obj
        self._graph.add_node(obj.id, object=obj)

    def add_dependency(
        self,
        source_id: UUID,
        target_id: UUID,
        dep_type: DependencyType = DependencyType.REFERENCES,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Add a directed edge from source to target."""
        if source_id not in self._graph or target_id not in self._graph:
            raise ValueError("Both source and target must be added as objects first.")
        self._graph.add_edge(
            source_id,
            target_id,
            dependency_type=dep_type,
            metadata=metadata or {},
        )

    def add_edges_from_dependencies(self, dependencies: list[DependencyEdge]) -> None:
        """Bulk add dependency edges."""
        for dep in dependencies:
            self.add_dependency(
                source_id=dep.source_id,
                target_id=dep.target_id,
                dep_type=dep.dependency_type,
                metadata=dep.metadata,
            )

    def topological_sort(self) -> list[UUID]:
        """Return object IDs in topological order (dependencies first).

        This determines the correct migration order: objects with no
        dependencies are migrated first.
        """
        try:
            return list(nx.topological_sort(self._graph))
        except nx.NetworkXUnfeasible:
            return []

    def get_circular_dependencies(self) -> list[CircularDependency]:
        """Detect circular dependencies using strongly connected components (SCC)."""
        sccs = list(nx.strongly_connected_components(self._graph))
        circular: list[CircularDependency] = []
        for scc in sccs:
            if len(scc) > 1:
                obj_names = []
                for node_id in scc:
                    obj = self._object_map.get(node_id)
                    if obj:
                        obj_names.append(obj.fully_qualified_name)
                    else:
                        obj_names.append(str(node_id))
                circular.append(
                    CircularDependency(
                        object_ids=list(scc),
                        path_description=" -> ".join(obj_names),
                    )
                )
        return circular

    def get_dependency_order_groups(self) -> list[list[UUID]]:
        """Return objects grouped by dependency level.

        Level 0: No dependencies
        Level N: All dependencies are in levels < N
        """
        levels: dict[UUID, int] = {}
        topological = self.topological_sort()
        if not topological:
            return []

        for node_id in topological:
            predecessors = list(self._graph.predecessors(node_id))
            if not predecessors:
                levels[node_id] = 0
            else:
                levels[node_id] = max(levels.get(p, 0) for p in predecessors) + 1

        groups: dict[int, list[UUID]] = {}
        for node_id, level in levels.items():
            groups.setdefault(level, []).append(node_id)

        max_level = max(groups.keys()) if groups else 0
        return [groups.get(i, []) for i in range(max_level + 1)]

    def get_dependents_of(self, object_id: UUID) -> list[UUID]:
        """Get all objects that depend on the given object."""
        return list(nx.descendants(self._graph, object_id)) if object_id in self._graph else []

    def get_dependencies_of(self, object_id: UUID) -> list[UUID]:
        """Get all objects that the given object depends on."""
        return list(nx.ancestors(self._graph, object_id)) if object_id in self._graph else []

    def get_metadata(self) -> GraphMetadata:
        """Get metadata about the current graph state."""
        circular = self.get_circular_dependencies()
        node_types: dict[str, int] = {}
        for obj in self._object_map.values():
            node_types[obj.object_type.value] = node_types.get(obj.object_type.value, 0) + 1

        return GraphMetadata(
            total_nodes=self._graph.number_of_nodes(),
            total_edges=self._graph.number_of_edges(),
            circular_dependency_count=len(circular),
            node_types=node_types,
        )

    @property
    def graph(self) -> nx.DiGraph:
        return self._graph

    @property
    def object_count(self) -> int:
        return len(self._object_map)
