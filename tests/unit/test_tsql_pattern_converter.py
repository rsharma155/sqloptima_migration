"""
Module: tests/unit/test_tsql_pattern_converter.py
Purpose: Unit tests for TsqlPatternConverter — NOLOCK removal, MERGE conversion,
         FOR XML PATH, MAXRECURSION, and global temp table (##) flagging.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import pytest

from domains.transpilation.tsql_pattern_converter import TsqlPatternConverter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _convert(sql: str) -> tuple[str, list[str]]:
    result = TsqlPatternConverter().convert(sql)
    return result.sql, result.warnings


# ---------------------------------------------------------------------------
# NOLOCK removal
# ---------------------------------------------------------------------------


class TestNolockRemoval:
    def test_with_nolock_removed(self):
        sql = "SELECT * FROM dbo.orders WITH (NOLOCK)"
        out, warnings = _convert(sql)
        assert "WITH (NOLOCK)" not in out.upper()
        assert warnings

    def test_nolock_with_spaces_removed(self):
        sql = "SELECT * FROM orders WITH ( NOLOCK )"
        out, _ = _convert(sql)
        assert "NOLOCK" not in out.upper() or "⚠️" in out

    def test_nolock_warning_message_informative(self):
        sql = "SELECT id FROM t WITH (NOLOCK)"
        _, warnings = _convert(sql)
        assert any("nolock" in w.lower() or "NOLOCK" in w for w in warnings)

    def test_nolock_annotation_in_output(self):
        sql = "SELECT * FROM t WITH (NOLOCK) WHERE id = 1"
        out, _ = _convert(sql)
        assert "⚠️" in out or "READ COMMITTED" in out.upper() or "NOLOCK" in out.upper()

    def test_no_nolock_no_change(self):
        sql = "SELECT * FROM orders WHERE id = 1"
        out, warnings = _convert(sql)
        assert out == sql
        assert not any("nolock" in w.lower() for w in warnings)

    def test_multiple_nolock_all_removed(self):
        sql = "SELECT * FROM a WITH (NOLOCK) JOIN b WITH (NOLOCK) ON a.id = b.id"
        out, warnings = _convert(sql)
        assert "WITH (NOLOCK)" not in out.upper()
        assert warnings  # at least one warning generated


# ---------------------------------------------------------------------------
# FOR XML PATH conversion
# ---------------------------------------------------------------------------


class TestForXmlPath:
    def test_for_xml_path_annotated(self):
        sql = "SELECT id, name FROM t FOR XML PATH('row')"
        out, warnings = _convert(sql)
        assert "MANUAL REVIEW" in out or "⚠️" in out
        assert warnings

    def test_for_xml_auto_annotated(self):
        sql = "SELECT * FROM orders FOR XML AUTO"
        out, warnings = _convert(sql)
        assert "MANUAL REVIEW" in out.upper() or "⚠️" in out

    def test_for_json_path_annotated(self):
        sql = "SELECT id, name FROM users FOR JSON PATH"
        out, warnings = _convert(sql)
        assert "MANUAL REVIEW" in out.upper() or "⚠️" in out
        assert warnings

    def test_no_for_xml_no_change(self):
        sql = "SELECT id FROM t WHERE id = 1"
        out, warnings = _convert(sql)
        assert out == sql
        assert not any("xml" in w.lower() for w in warnings)


# ---------------------------------------------------------------------------
# MAXRECURSION
# ---------------------------------------------------------------------------


class TestMaxrecursion:
    def test_maxrecursion_replaced_with_comment(self):
        sql = "WITH cte AS (SELECT 1) SELECT * FROM cte OPTION (MAXRECURSION 100)"
        out, warnings = _convert(sql)
        assert "OPTION (MAXRECURSION" not in out.upper()
        assert "max_recursion_depth" in out.lower() or "MAXRECURSION" in out
        assert warnings

    def test_maxrecursion_preserves_depth_value(self):
        sql = "SELECT 1 OPTION (MAXRECURSION 50)"
        out, warnings = _convert(sql)
        assert "50" in out

    def test_no_maxrecursion_no_change(self):
        sql = "SELECT * FROM t"
        out, warnings = _convert(sql)
        assert out == sql
        assert not warnings


# ---------------------------------------------------------------------------
# Global temp tables (##)
# ---------------------------------------------------------------------------


class TestGlobalTempTables:
    def test_double_hash_flagged(self):
        sql = "SELECT * INTO ##staging FROM orders"
        out, warnings = _convert(sql)
        assert "##staging" not in out
        assert "tmp_staging" in out.lower()
        assert any("##staging" in w or "global temp" in w.lower() for w in warnings)

    def test_annotation_is_manual_review(self):
        sql = "INSERT INTO ##temp_results SELECT id FROM t"
        out, warnings = _convert(sql)
        assert "MANUAL REVIEW" in out.upper()

    def test_multiple_global_temps_flagged(self):
        sql = "SELECT * FROM ##a UNION ALL SELECT * FROM ##b"
        out, warnings = _convert(sql)
        assert "##a" not in out
        assert "##b" not in out
        assert any("##a" in w or "##b" in w for w in warnings)

    def test_single_hash_temp_not_affected(self):
        # Single # local temp tables are valid in PG procedures via TEMP TABLE syntax
        sql = "SELECT * FROM #local_temp WHERE id = 1"
        out, warnings = _convert(sql)
        assert "#local_temp" in out  # unchanged — single hash is not targeted
        assert not any("global temp" in w.lower() for w in warnings)


# ---------------------------------------------------------------------------
# MERGE conversion
# ---------------------------------------------------------------------------


class TestMergeConversion:
    def test_simple_merge_converted(self):
        sql = """
MERGE dbo.customers AS t
USING staging_customers AS s ON t.customer_id = s.customer_id
WHEN MATCHED THEN UPDATE SET t.name = s.name, t.email = s.email
WHEN NOT MATCHED THEN INSERT (customer_id, name, email) VALUES (s.customer_id, s.name, s.email);
"""
        out, warnings = _convert(sql)
        assert "ON CONFLICT" in out.upper()
        assert "INSERT INTO" in out.upper()
        assert warnings

    def test_complex_merge_gets_annotation(self):
        sql = "MERGE dbo.t USING src ON t.id = src.id WHEN NOT MATCHED BY SOURCE THEN DELETE;"
        out, warnings = _convert(sql)
        assert "MANUAL REVIEW" in out.upper()
        assert warnings

    def test_merge_warning_generated(self):
        sql = "MERGE INTO target USING src ON target.id = src.id WHEN MATCHED THEN UPDATE SET target.v = src.v WHEN NOT MATCHED THEN INSERT (id, v) VALUES (src.id, src.v);"
        _, warnings = _convert(sql)
        assert any("merge" in w.lower() for w in warnings)

    def test_manual_review_flag(self):
        sql = "MERGE complex_table USING (...)"
        result = TsqlPatternConverter().convert(sql)
        assert result.manual_review_required


# ---------------------------------------------------------------------------
# Combined conversions
# ---------------------------------------------------------------------------


class TestCombinedConversions:
    def test_nolock_and_for_xml_both_handled(self):
        sql = "SELECT * FROM t WITH (NOLOCK) FOR XML PATH('row')"
        out, warnings = _convert(sql)
        assert "WITH (NOLOCK)" not in out.upper()
        assert "FOR XML" not in out.upper() or "⚠️" in out
        assert len(warnings) >= 2

    def test_empty_sql_unchanged(self):
        sql = ""
        out, warnings = _convert(sql)
        assert out == ""
        assert warnings == []
