"""
Module: test_ir_builder.py
Purpose: Unit tests for IR builder
Author: Migration Platform Team
Created: 2026-05-22
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

import pytest

from domains.parsing.sqlglot_adapter import SqlglotParser
from domains.transpilation.ir_builder import IrBuilder
from domains.transpilation.ir_models import IrNodeType


@pytest.fixture
def ir_builder():
    parser = SqlglotParser()
    return IrBuilder(parser)


class TestIrBuilder:
    def test_build_simple_select(self, ir_builder):
        ir = ir_builder.build_from_sql("SELECT 1")
        assert ir is not None
        assert ir.node_type == IrNodeType.PROGRAM
        assert len(ir.statements) > 0

    def test_build_create_table(self, ir_builder):
        sql = "CREATE TABLE dbo.users (id INT NOT NULL, name VARCHAR(100))"
        ir = ir_builder.build_from_sql(sql)
        assert ir is not None
        assert len(ir.statements) > 0

    def test_build_multiple_statements(self, ir_builder):
        sql = "SELECT 1; SELECT 2"
        ir = ir_builder.build_multiple(sql)
        assert ir is not None
        assert len(ir.statements) >= 2

    def test_build_invalid_sql_returns_none(self, ir_builder):
        ir = ir_builder.build_from_sql("SELEC 1 FROM")
        assert ir is None
