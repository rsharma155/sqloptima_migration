"""Tests for CFG Builder, Variable Scope Resolver, and TVP Converter.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

import pytest

from domains.transpilation.procedural_converter import (
    CFGNode,
    ControlFlowGraph,
    ControlFlowGraphBuilder,
    ScopeBlock,
    TvpConverter,
    TvpTypeDefinition,
    TvpUsage,
    Variable,
    VariableScopeResolver,
)

# ---- CFG Builder Tests (Phase 4.4) ----

class TestCFGNode:
    def test_create_node(self):
        node = CFGNode(node_id=1, label="START", statement_type="entry")
        assert node.node_id == 1
        assert node.label == "START"
        assert node.children == []

    def test_add_child(self):
        parent = CFGNode(node_id=1, label="P")
        child = CFGNode(node_id=2, label="C")
        parent.children.append(child)
        child.parent = parent
        assert len(parent.children) == 1
        assert child.parent == parent


class TestControlFlowGraph:
    def test_add_node(self):
        cfg = ControlFlowGraph()
        n1 = cfg.add_node("START", "entry")
        cfg.add_node("END", "return")
        assert len(cfg.nodes) == 2
        assert cfg.get_entry() == n1

    def test_add_edge(self):
        cfg = ControlFlowGraph()
        n1 = cfg.add_node("A")
        n2 = cfg.add_node("B")
        cfg.add_edge(n1, n2)
        assert n2 in n1.children
        assert n2.parent == n1

    def test_find_node(self):
        cfg = ControlFlowGraph()
        cfg.add_node("IF condition", "if")
        found = cfg.find_node(lambda n: n.statement_type == "if")
        assert found is not None
        assert found.label == "IF condition"

    def test_find_all(self):
        cfg = ControlFlowGraph()
        cfg.add_node("ASSIGN a=1", "assignment")
        cfg.add_node("ASSIGN b=2", "assignment")
        cfg.add_node("RETURN", "return")
        all_assign = cfg.find_all(lambda n: n.statement_type == "assignment")
        assert len(all_assign) == 2


class TestControlFlowGraphBuilder:
    @pytest.fixture
    def builder(self):
        return ControlFlowGraphBuilder()

    def test_build_simple(self, builder):
        cfg = builder.build("SELECT 1;")
        assert len(cfg.nodes) >= 2  # entry + statement

    def test_build_with_if(self, builder):
        sql = """
        IF @count > 0
        BEGIN
            SELECT @count;
        END
        """
        cfg = builder.build(sql)
        if_nodes = cfg.find_all(lambda n: n.statement_type == "if")
        assert len(if_nodes) >= 1

    def test_build_with_while(self, builder):
        sql = """
        WHILE @i < 10
        BEGIN
            SET @i = @i + 1;
        END
        """
        cfg = builder.build(sql)
        loop_nodes = cfg.find_all(lambda n: n.statement_type == "loop")
        assert len(loop_nodes) >= 1

    def test_build_with_goto(self, builder):
        sql = """
        IF @error = 1
            GOTO error_handler;
        RETURN;
        error_handler:
            PRINT 'Error';
        """
        cfg = builder.build(sql)
        goto_nodes = cfg.find_all(lambda n: n.statement_type == "goto")
        assert len(goto_nodes) >= 1

    def test_build_with_cursor(self, builder):
        sql = """
        DECLARE c CURSOR FOR SELECT id FROM users;
        OPEN c;
        FETCH NEXT FROM c INTO @id;
        """
        cfg = builder.build(sql)
        cursor_nodes = cfg.find_all(lambda n: n.statement_type == "cursor")
        assert len(cursor_nodes) >= 1

    def test_build_empty(self, builder):
        cfg = builder.build("")
        assert len(cfg.nodes) >= 1  # at least the entry node

    def test_to_mermaid(self, builder):
        cfg = builder.build("SELECT 1;")
        mermaid = builder.to_mermaid(cfg)
        assert "graph TD;" in mermaid
        assert "N1" in mermaid


# ---- Variable Scope Resolver Tests (Phase 4.5) ----

class TestVariable:
    def test_create(self):
        v = Variable(name="@id", data_type="INT", declared_line=5)
        assert v.name == "@id"
        assert v.declared_line == 5

    def test_is_cursor(self):
        v = Variable(name="@c", data_type="CURSOR", is_cursor=True)
        assert v.is_cursor is True

    def test_is_table_variable(self):
        v = Variable(name="@t", data_type="TABLE", is_table_variable=True)
        assert v.is_table_variable is True


class TestScopeBlock:
    def test_create(self):
        sb = ScopeBlock(block_id=0, start_line=1)
        assert sb.block_id == 0
        assert sb.variables == []


class TestVariableScopeResolver:
    @pytest.fixture
    def resolver(self):
        return VariableScopeResolver()

    def test_resolve_declare_int(self, resolver):
        resolver.resolve("DECLARE @id INT;")
        v = resolver.get_variable("@id")
        assert v is not None
        assert v.data_type == "INT"
        assert v.declared_line == 1

    def test_resolve_declare_varchar(self, resolver):
        resolver.resolve("DECLARE @name VARCHAR(100);")
        v = resolver.get_variable("@name")
        assert v is not None
        assert "VARCHAR" in v.data_type.upper()

    def test_resolve_multiple_declares(self, resolver):
        sql = """
        DECLARE @id INT;
        DECLARE @name NVARCHAR(100);
        DECLARE @price DECIMAL(10,2);
        """
        resolver.resolve(sql)
        assert resolver.get_variable("@id") is not None
        assert resolver.get_variable("@name") is not None
        assert resolver.get_variable("@price") is not None

    def test_usage_tracking(self, resolver):
        sql = """
        DECLARE @total INT;
        SET @total = 100;
        SELECT @total;
        """
        resolver.resolve(sql)
        v = resolver.get_variable("@total")
        assert v is not None
        assert len(v.used_in_lines) >= 1

    def test_unused_variables(self, resolver):
        resolver.resolve("DECLARE @unused INT;")
        unused = resolver.find_unused_variables()
        assert len(unused) == 1

    def test_no_unused(self, resolver):
        resolver.resolve("DECLARE @used INT;\nSELECT @used;")
        unused = resolver.find_unused_variables()
        assert len(unused) == 0

    def test_scope_blocks(self, resolver):
        sql = """
        BEGIN
            DECLARE @x INT;
        END
        """
        scopes = resolver.resolve(sql)
        assert len(scopes) >= 1  # root + inner

    def test_empty_sql(self, resolver):
        scopes = resolver.resolve("")
        assert len(scopes) >= 1


# ---- TVP Converter Tests (Phase 4.10) ----

class TestTvpTypeDefinition:
    def test_create(self):
        td = TvpTypeDefinition(
            type_name="dbo.udt_StringList",
            columns=[{"name": "value", "type": "NVARCHAR(100)"}],
        )
        assert td.type_name == "dbo.udt_StringList"
        assert len(td.columns) == 1


class TestTvpUsage:
    def test_create(self):
        tu = TvpUsage(
            variable_name="@items",
            type_name="dbo.udt_ItemList",
            columns=[{"name": "id", "type": "INT"}],
        )
        assert tu.variable_name == "@items"


class TestTvpConverter:
    @pytest.fixture
    def converter(self):
        c = TvpConverter()
        c.register_type(TvpTypeDefinition(
            type_name="dbo.udt_StringList",
            columns=[{"name": "value", "type": "NVARCHAR(100)"}],
        ))
        return c

    def test_register_type(self, converter):
        assert converter._type_definitions["DBO.UDT_STRINGLIST"] is not None

    def test_analyze_declare_tvp(self, converter):
        usages = converter.analyze("DECLARE @items AS dbo.udt_StringList;")
        assert len(usages) >= 1
        assert usages[0].variable_name == "@items"

    def test_analyze_no_tvp(self, converter):
        usages = converter.analyze("SELECT 1;")
        assert len(usages) == 0

    def test_convert_to_jsonb(self, converter):
        usage = TvpUsage(
            variable_name="@items",
            type_name="dbo.udt_StringList",
            columns=[{"name": "value", "type": "NVARCHAR(100)"}],
        )
        result = converter.convert_to_jsonb(usage)
        assert "jsonb_to_recordset" in result
        assert "p_data" in result

    def test_convert_to_temp_table(self, converter):
        usage = TvpUsage(
            variable_name="@items",
            type_name="dbo.udt_StringList",
            columns=[{"name": "value", "type": "NVARCHAR(100)"}],
        )
        result = converter.convert_to_temp_table(usage, "input_data")
        assert "CREATE TEMPORARY TABLE" in result
        assert "input_data" in result

    def test_map_type_int(self):
        assert TvpConverter._map_type("INT") == "INTEGER"

    def test_map_type_varchar(self):
        assert TvpConverter._map_type("NVARCHAR(100)") == "TEXT"

    def test_map_type_datetime(self):
        assert TvpConverter._map_type("DATETIME") == "TIMESTAMP"
