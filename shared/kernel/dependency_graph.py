"""
Module: dependency_graph.py
Purpose: Value objects for dependency graph (nodes, edges, graph metadata)
Author: Migration Platform Team
Created: 2026-05-22
Domain: Lineage
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import Field

from shared.kernel.base_entity import ValueObject


class DependencyType(StrEnum):
    REFERENCES = "references"
    CALLS = "calls"
    USES = "uses"
    EXTENDS = "extends"
    CONTAINS = "contains"


class DependencyEdge(ValueObject):
    """Represents a directed edge between two database objects."""

    source_id: UUID
    target_id: UUID
    dependency_type: DependencyType = DependencyType.REFERENCES
    metadata: dict[str, Any] = Field(default_factory=dict)


class GraphMetadata(ValueObject):
    """Metadata about the dependency graph."""

    total_nodes: int = 0
    total_edges: int = 0
    circular_dependency_count: int = 0
    node_types: dict[str, int] = Field(default_factory=dict)


class CircularDependency(ValueObject):
    """Represents a circular dependency found in the graph."""

    object_ids: list[UUID]
    path_description: str
