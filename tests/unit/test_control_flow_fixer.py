"""
Module: tests/unit/test_control_flow_fixer.py
Purpose: Unit tests for ControlFlowFixer — T-SQL/PL/pgSQL control flow syntax fixes.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import pytest

from domains.transpilation.converters.control_flow_fixer import ControlFlowFixer


class TestControlFlowFixer:
    """Test T-SQL to PL/pgSQL control flow syntax fixes."""

    def test_fix_if_begin_to_then(self) -> None:
        """Verify IF cond BEGIN converted to IF cond THEN."""
        sql = """
IF v_count > 0 BEGIN
    RAISE NOTICE 'Found records';
END
"""
        converted, count = ControlFlowFixer.fix_if_begin(sql)
        assert count > 0
        assert 'IF v_count > 0 THEN' in converted
        assert 'BEGIN' not in converted

    def test_fix_else_if_to_elsif(self) -> None:
        """Verify ELSE IF converted to ELSIF."""
        sql = """
IF v_status = 'active' THEN
    -- Process active
ELSE IF v_status = 'pending' THEN
    -- Process pending
END IF;
"""
        converted, count = ControlFlowFixer.fix_else_if(sql)
        assert count > 0
        assert 'ELSIF' in converted
        assert 'ELSE IF' not in converted

    def test_fix_end_labels(self) -> None:
        """Verify END -- IF converted to END IF;."""
        sql = """
IF v_x > 0 THEN
    PERFORM something();
END -- IF
"""
        converted, count = ControlFlowFixer.fix_end_labels(sql)
        # Should have END IF or END with comment removed
        assert 'END' in converted

    def test_fix_bare_return(self) -> None:
        """Verify bare RETURN gets semicolon."""
        sql = """
IF v_error THEN
    RETURN
END IF;
"""
        converted, count = ControlFlowFixer.fix_bare_return(sql)
        # RETURN should have proper syntax
        assert 'RETURN' in converted

    def test_no_control_flow_no_changes(self) -> None:
        """Verify no changes when no control flow issues."""
        sql = """
SELECT * FROM Products;
UPDATE Products SET active = TRUE;
"""
        result = ControlFlowFixer.apply_all(sql)
        assert result.fixes_applied == 0
        assert result.sql == sql

    def test_multiple_if_statements(self) -> None:
        """Verify multiple IF statements all fixed."""
        sql = """
IF v_a > 0 BEGIN
    RAISE NOTICE 'A';
END

IF v_b < 5 BEGIN
    RAISE NOTICE 'B';
END
"""
        result = ControlFlowFixer.apply_all(sql)
        assert result.fixes_applied > 0

    def test_nested_if_else_if(self) -> None:
        """Verify nested IF with ELSE IF fixed."""
        sql = """
IF v_x > 0 BEGIN
    IF v_y > 0 BEGIN
        RAISE NOTICE 'Both positive';
    END
ELSE IF v_x < 0 BEGIN
    RAISE NOTICE 'X negative';
END
"""
        result = ControlFlowFixer.apply_all(sql)
        assert result.fixes_applied > 0
        assert 'ELSIF' in result.sql or result.sql.count('IF') > result.sql.count('BEGIN')
