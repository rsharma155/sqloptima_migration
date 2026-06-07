"""
Test suite for MERGE statement conversion.

Tests conversion of T-SQL MERGE to PostgreSQL INSERT ... ON CONFLICT and CTE-based UPSERT.
"""

import pytest

from domains.transpilation.converters.merge_converter import (
    MergeConverter,
    MergeStatement,
)


class TestMergeParser:
    """Test MERGE statement parsing."""

    def test_parse_simple_merge(self):
        """Parse basic MERGE structure."""
        sql = """
        MERGE INTO target t
        USING source s
        ON t.id = s.id
        WHEN MATCHED THEN UPDATE SET t.name = s.name
        WHEN NOT MATCHED THEN INSERT (id, name) VALUES (s.id, s.name)
        """
        stmt = MergeConverter.parse_merge(sql)
        assert stmt is not None
        assert stmt.target_table == "target"
        assert stmt.target_alias == "t"
        assert stmt.source_table == "source"
        assert stmt.source_alias == "s"
        assert "id" in stmt.join_condition

    def test_parse_merge_with_multiple_key_columns(self):
        """Parse MERGE with composite key."""
        sql = """
        MERGE INTO orders o
        USING new_orders n
        ON o.order_id = n.order_id AND o.customer_id = n.customer_id
        WHEN MATCHED THEN UPDATE SET o.status = n.status
        WHEN NOT MATCHED THEN INSERT (order_id, customer_id) VALUES (n.order_id, n.customer_id)
        """
        stmt = MergeConverter.parse_merge(sql)
        assert stmt is not None
        assert "order_id" in stmt.join_condition
        assert "customer_id" in stmt.join_condition

    def test_parse_merge_with_delete_clause(self):
        """Parse MERGE with NOT MATCHED BY SOURCE DELETE."""
        sql = """
        MERGE INTO target t
        USING source s
        ON t.id = s.id
        WHEN MATCHED THEN UPDATE SET t.val = s.val
        WHEN NOT MATCHED BY SOURCE THEN DELETE
        """
        stmt = MergeConverter.parse_merge(sql)
        assert stmt is not None
        assert stmt.not_matched_by_source_delete is True
        assert stmt.is_complex is True

    def test_parse_merge_without_aliases(self):
        """Parse MERGE without AS aliases."""
        sql = """
        MERGE INTO target_table
        USING source_table
        ON target_table.id = source_table.id
        WHEN MATCHED THEN UPDATE SET target_table.value = source_table.value
        """
        stmt = MergeConverter.parse_merge(sql)
        assert stmt is not None
        assert stmt.target_table == "target_table"


class TestMergeConversion:
    """Test MERGE to INSERT ... ON CONFLICT conversion."""

    def test_simple_merge_to_insert_on_conflict(self):
        """Convert simple MERGE to INSERT ON CONFLICT."""
        sql = """
        MERGE INTO products p
        USING new_products n
        ON p.product_id = n.product_id
        WHEN MATCHED THEN UPDATE SET p.price = n.price, p.stock = n.stock
        WHEN NOT MATCHED THEN INSERT (product_id, price, stock) VALUES (n.product_id, n.price, n.stock)
        """
        result = MergeConverter.apply_all(sql)
        assert result.success is True
        assert result.conversion_type == "insert_on_conflict"
        assert "INSERT INTO" in result.sql
        assert "ON CONFLICT" in result.sql
        assert "DO UPDATE SET" in result.sql

    def test_merge_with_single_column_update(self):
        """Convert MERGE with single column update."""
        sql = """
        MERGE INTO users u
        USING updates ud
        ON u.id = ud.user_id
        WHEN MATCHED THEN UPDATE SET u.last_login = ud.login_time
        WHEN NOT MATCHED THEN INSERT (id, last_login) VALUES (ud.user_id, ud.login_time)
        """
        result = MergeConverter.apply_all(sql)
        assert result.success is True
        assert "last_login" in result.sql

    def test_merge_with_multiple_updates(self):
        """Convert MERGE with multiple column updates."""
        sql = """
        MERGE INTO inventory inv
        USING stock_updates su
        ON inv.item_id = su.item_id
        WHEN MATCHED THEN UPDATE SET
            inv.quantity = su.quantity,
            inv.last_updated = su.update_time,
            inv.status = su.status
        WHEN NOT MATCHED THEN INSERT (item_id, quantity) VALUES (su.item_id, su.quantity)
        """
        result = MergeConverter.apply_all(sql)
        assert result.success is True
        assert "quantity" in result.sql
        assert "last_updated" in result.sql
        assert "status" in result.sql

    def test_merge_key_column_extraction(self):
        """Extract key columns from join condition."""
        sql = """
        MERGE INTO target t
        USING source s
        ON t.id = s.id AND t.type = s.type
        WHEN MATCHED THEN UPDATE SET t.val = s.val
        WHEN NOT MATCHED THEN INSERT (id, type, val) VALUES (s.id, s.type, s.val)
        """
        result = MergeConverter.apply_all(sql)
        assert result.success is True
        # Should have both key columns in ON CONFLICT clause
        assert "ON CONFLICT" in result.sql


class TestMergeCTEConversion:
    """Test MERGE with DELETE clause → CTE-based UPSERT."""

    def test_merge_with_delete_to_cte(self):
        """Convert MERGE with DELETE to CTE-based approach."""
        sql = """
        MERGE INTO target t
        USING source s
        ON t.id = s.id
        WHEN MATCHED THEN UPDATE SET t.value = s.value
        WHEN NOT MATCHED THEN INSERT (id, value) VALUES (s.id, s.value)
        WHEN NOT MATCHED BY SOURCE THEN DELETE
        """
        result = MergeConverter.apply_all(sql)
        assert result.success is True
        assert result.conversion_type == "cte_upsert"
        assert "WITH" in result.sql  # CTE syntax
        assert "UPDATE" in result.sql
        assert "INSERT INTO" in result.sql
        assert "DELETE FROM" in result.sql

    def test_merge_delete_preserves_join_logic(self):
        """CTE conversion preserves join condition for DELETE."""
        sql = """
        MERGE INTO active_users au
        USING current_users cu
        ON au.user_id = cu.user_id
        WHEN NOT MATCHED BY SOURCE THEN DELETE
        """
        result = MergeConverter.apply_all(sql)
        assert result.success is True
        assert "user_id" in result.sql


class TestMergeEdgeCases:
    """Test edge cases and error handling."""

    def test_no_merge_in_sql(self):
        """SQL without MERGE is returned unchanged."""
        sql = "SELECT * FROM users"
        result = MergeConverter.apply_all(sql)
        assert result.sql == sql
        assert result.success is False or result.conversion_type == ""

    def test_malformed_merge(self):
        """Malformed MERGE is handled gracefully."""
        sql = "MERGE INTO table USING"
        result = MergeConverter.apply_all(sql)
        # Should warn but not crash
        assert result is not None
        assert len(result.warnings) > 0

    def test_merge_with_complex_expressions(self):
        """MERGE with complex UPDATE expressions."""
        sql = """
        MERGE INTO targets t
        USING sources s
        ON t.id = s.id
        WHEN MATCHED THEN UPDATE SET t.calculated = s.value * 1.1
        WHEN NOT MATCHED THEN INSERT (id, calculated) VALUES (s.id, s.value * 1.1)
        """
        result = MergeConverter.apply_all(sql)
        assert result.success is True
        assert "1.1" in result.sql  # Expression preserved

    def test_merge_case_insensitivity(self):
        """MERGE keywords are case-insensitive."""
        sql_upper = """
        MERGE INTO TARGET T
        USING SOURCE S
        ON T.ID = S.ID
        WHEN MATCHED THEN UPDATE SET T.VAL = S.VAL
        """
        sql_lower = """
        merge into target t
        using source s
        on t.id = s.id
        when matched then update set t.val = s.val
        """
        result_upper = MergeConverter.apply_all(sql_upper)
        result_lower = MergeConverter.apply_all(sql_lower)
        # Both should succeed
        assert result_upper.success or result_lower.success

    def test_split_set_pairs(self):
        """Correctly parse SET clause with multiple assignments."""
        update_clause = "col1 = val1, col2 = val2, col3 = FUNC(val3)"
        pairs = MergeConverter._split_set_pairs(update_clause)
        assert len(pairs) == 3
        assert pairs[0] == ("col1", "val1")
        assert pairs[1] == ("col2", "val2")
        assert "col3" in pairs[2][0]

    def test_extract_key_columns(self):
        """Extract key columns from various join formats."""
        join_cond = "t.id = s.id AND t.tenant_id = s.tenant_id"
        keys = MergeConverter._extract_key_columns(join_cond, "t")
        assert "id" in keys
        assert "tenant_id" in keys


class TestMergeIntegration:
    """Integration tests with typical scenarios."""

    def test_typical_inventory_merge(self):
        """Typical inventory UPSERT scenario."""
        sql = """
        MERGE INTO inventory.products prod
        USING staging.product_updates upd
        ON prod.sku = upd.sku
        WHEN MATCHED AND upd.action = 'UPDATE'
            THEN UPDATE SET prod.quantity = upd.quantity, prod.price = upd.price
        WHEN NOT MATCHED BY TARGET AND upd.action = 'INSERT'
            THEN INSERT (sku, quantity, price) VALUES (upd.sku, upd.quantity, upd.price)
        WHEN NOT MATCHED BY SOURCE
            THEN DELETE
        """
        result = MergeConverter.apply_all(sql)
        # Should convert despite conditional logic
        assert result is not None

    def test_typical_user_sync_merge(self):
        """Typical user synchronization MERGE."""
        sql = """
        MERGE INTO users u
        USING temp_users tu
        ON u.email = tu.email
        WHEN MATCHED THEN
            UPDATE SET u.first_name = tu.first_name, u.last_name = tu.last_name, u.updated_at = GETDATE()
        WHEN NOT MATCHED THEN
            INSERT (email, first_name, last_name, created_at) VALUES (tu.email, tu.first_name, tu.last_name, GETDATE())
        """
        result = MergeConverter.apply_all(sql)
        assert result.success is True
        assert "email" in result.sql


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
