"""
Module: test_dependency_graph.py
Purpose: Unit tests for dependency graph engine
Author: Migration Platform Team
Created: 2026-05-22
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from uuid import UUID

import pytest

from domains.lineage.dependency_graph_engine import DependencyGraphEngine
from shared.kernel.database_object import DatabaseObject, DatabaseObjectType
from shared.kernel.dependency_graph import DependencyEdge


@pytest.fixture
def graph_engine():
    return DependencyGraphEngine()


@pytest.fixture
def sample_objects():
    return [
        DatabaseObject(
            id=UUID("00000000-0000-0000-0000-000000000001"),
            object_type=DatabaseObjectType.TABLE,
            database_name="db",
            schema_name="dbo",
            object_name="users",
        ),
        DatabaseObject(
            id=UUID("00000000-0000-0000-0000-000000000002"),
            object_type=DatabaseObjectType.VIEW,
            database_name="db",
            schema_name="dbo",
            object_name="v_user_details",
        ),
        DatabaseObject(
            id=UUID("00000000-0000-0000-0000-000000000003"),
            object_type=DatabaseObjectType.PROCEDURE,
            database_name="db",
            schema_name="dbo",
            object_name="usp_get_users",
        ),
        DatabaseObject(
            id=UUID("00000000-0000-0000-0000-000000000004"),
            object_type=DatabaseObjectType.FUNCTION,
            database_name="db",
            schema_name="dbo",
            object_name="fn_format_name",
        ),
    ]


class TestDependencyGraphEngine:
    def test_add_object(self, graph_engine):
        obj = DatabaseObject(
            object_type=DatabaseObjectType.TABLE,
            database_name="db",
            schema_name="dbo",
            object_name="test",
        )
        graph_engine.add_object(obj)
        assert graph_engine.object_count == 1
        assert graph_engine.get_metadata().total_nodes == 1

    def test_add_dependency(self, graph_engine, sample_objects):
        for obj in sample_objects:
            graph_engine.add_object(obj)

        graph_engine.add_dependency(
            source_id=sample_objects[0].id,
            target_id=sample_objects[1].id,
        )
        meta = graph_engine.get_metadata()
        assert meta.total_edges == 1

    def test_add_dependency_invalid_node(self, graph_engine):
        obj = DatabaseObject(
            object_type=DatabaseObjectType.TABLE,
            database_name="db",
            schema_name="dbo",
            object_name="test",
        )
        graph_engine.add_object(obj)

        with pytest.raises(ValueError):
            graph_engine.add_dependency(
                source_id=obj.id,
                target_id=UUID("00000000-0000-0000-0000-000000000999"),
            )

    def test_topological_sort_linear(self, graph_engine, sample_objects):
        for obj in sample_objects:
            graph_engine.add_object(obj)

        # Table (0) -> View (1) -> Function (3) -> Procedure (2)
        graph_engine.add_dependency(sample_objects[0].id, sample_objects[1].id)
        graph_engine.add_dependency(sample_objects[1].id, sample_objects[3].id)
        graph_engine.add_dependency(sample_objects[3].id, sample_objects[2].id)

        order = graph_engine.topological_sort()
        assert len(order) == 4

        # Ensure dependencies come before dependents
        table_idx = order.index(sample_objects[0].id)
        view_idx = order.index(sample_objects[1].id)
        func_idx = order.index(sample_objects[3].id)
        proc_idx = order.index(sample_objects[2].id)

        assert table_idx < view_idx
        assert view_idx < func_idx
        assert func_idx < proc_idx

    def test_topological_sort_no_deps(self, graph_engine, sample_objects):
        for obj in sample_objects:
            graph_engine.add_object(obj)

        order = graph_engine.topological_sort()
        assert len(order) == 4

    def test_circular_dependency_detection(self, graph_engine, sample_objects):
        for obj in sample_objects:
            graph_engine.add_object(obj)

        # Create circular: View (1) <-> Function (3)
        graph_engine.add_dependency(sample_objects[1].id, sample_objects[3].id)
        graph_engine.add_dependency(sample_objects[3].id, sample_objects[1].id)

        circular = graph_engine.get_circular_dependencies()
        assert len(circular) > 0

    def test_dependency_order_groups(self, graph_engine, sample_objects):
        for obj in sample_objects:
            graph_engine.add_object(obj)

        graph_engine.add_dependency(sample_objects[0].id, sample_objects[1].id)
        graph_engine.add_dependency(sample_objects[1].id, sample_objects[2].id)

        groups = graph_engine.get_dependency_order_groups()
        assert len(groups) >= 1

        # Level 0: nodes with no dependencies
        level0 = set()
        for g in groups:
            level0.update(g)
        assert len(level0) == 4

    def test_get_dependents(self, graph_engine, sample_objects):
        for obj in sample_objects:
            graph_engine.add_object(obj)

        graph_engine.add_dependency(sample_objects[0].id, sample_objects[1].id)
        graph_engine.add_dependency(sample_objects[1].id, sample_objects[2].id)

        dependents = graph_engine.get_dependents_of(sample_objects[0].id)
        assert sample_objects[1].id in dependents
        assert sample_objects[2].id in dependents

    def test_get_dependencies(self, graph_engine, sample_objects):
        for obj in sample_objects:
            graph_engine.add_object(obj)

        graph_engine.add_dependency(sample_objects[0].id, sample_objects[1].id)

        deps = graph_engine.get_dependencies_of(sample_objects[1].id)
        assert sample_objects[0].id in deps

    def test_metadata(self, graph_engine, sample_objects):
        for obj in sample_objects:
            graph_engine.add_object(obj)

        graph_engine.add_dependency(sample_objects[0].id, sample_objects[1].id)

        meta = graph_engine.get_metadata()
        assert meta.total_nodes == 4
        assert meta.total_edges == 1
        assert meta.circular_dependency_count == 0
        assert "table" in meta.node_types
        assert meta.node_types["table"] == 1

    def test_add_edges_from_dependencies(self, graph_engine, sample_objects):
        for obj in sample_objects:
            graph_engine.add_object(obj)

        edges = [
            DependencyEdge(
                source_id=sample_objects[0].id,
                target_id=sample_objects[1].id,
            ),
            DependencyEdge(
                source_id=sample_objects[1].id,
                target_id=sample_objects[2].id,
            ),
        ]
        graph_engine.add_edges_from_dependencies(edges)
        assert graph_engine.get_metadata().total_edges == 2

    def test_empty_graph(self, graph_engine):
        assert graph_engine.object_count == 0
        assert graph_engine.topological_sort() == []
        assert graph_engine.get_circular_dependencies() == []
        assert graph_engine.get_dependency_order_groups() == []
