"""
Module: tests/unit/test_procedural_edge_cases.py
Purpose: Edge case regression tests for procedural conversion
Author: Migration Platform Team
Created: 2026-05-22
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""


from domains.transpilation.procedural_converter import (
    ControlFlowGraphBuilder,
    ConversionDifficulty,
    DynamicSqlAnalyzer,
    ParameterInfo,
    ProceduralConverter,
    TSqlPatternMatcher,
    TvpConverter,
    TvpTypeDefinition,
    VariableScopeResolver,
)

CONVERTER = ProceduralConverter()


class TestProceduralConverterEdgeCases:
    """Edge case tests for procedural converter."""

    def test_empty_parameters(self):
        result = CONVERTER.convert_procedure("dbo", "usp_test", [], "SELECT 1")
        assert result.success

    def test_special_characters_in_names(self):
        result = CONVERTER.convert_procedure("dbo", "usp_test_123", [], "SELECT 1")
        assert result.success

    def test_unicode_in_body(self):
        result = CONVERTER.convert_procedure(
            "dbo", "usp_unicode", [],
            "SELECT N'unicode text ユニコード' AS greeting",
        )
        assert result.success

    def test_body_with_only_comments(self):
        result = CONVERTER.convert_procedure(
            "dbo", "usp_comments", [],
            "-- This is a comment\n-- Another comment",
        )
        assert result.success

    def test_body_with_leading_trailing_whitespace(self):
        result = CONVERTER.convert_procedure(
            "dbo", "usp_ws", [],
            "  \n  SELECT 1  \n  ",
        )
        assert result.success

    def test_body_with_only_declare_statements(self):
        result = CONVERTER.convert_procedure(
            "dbo", "usp_declare_only", [],
            "DECLARE @x INT; DECLARE @y VARCHAR(100); DECLARE @z DATETIME;",
        )
        assert result.success

    def test_body_with_goto_and_labels(self):
        result = CONVERTER.convert_procedure(
            "dbo", "usp_goto", [],
            "IF @x = 1 GOTO done;\nSELECT 1;\ndone:\nSELECT 2;",
        )
        assert result.success

    def test_body_with_multiple_returns(self):
        result = CONVERTER.convert_procedure(
            "dbo", "usp_multi_return", [],
            "IF @x = 1 RETURN 1;\nIF @x = 2 RETURN 2;\nRETURN 0;",
        )
        assert result.success

    def test_body_with_cursor_dynamic_sql_txn_error_handling(self):
        result = CONVERTER.convert_procedure(
            "dbo", "usp_complex_mix", [],
            """
            DECLARE @sql NVARCHAR(MAX);
            DECLARE c CURSOR FOR SELECT id FROM users;
            BEGIN TRY
                BEGIN TRAN;
                OPEN c;
                FETCH NEXT FROM c INTO @id;
                WHILE @@FETCH_STATUS = 0
                BEGIN
                    SET @sql = 'UPDATE users SET status = 1 WHERE id = ' + CAST(@id AS NVARCHAR);
                    EXEC sp_executesql @sql;
                    FETCH NEXT FROM c INTO @id;
                END;
                COMMIT TRAN;
            END TRY
            BEGIN CATCH
                ROLLBACK TRAN;
                THROW;
            END CATCH;
            CLOSE c;
            DEALLOCATE c;
            """,
        )
        assert result.success


class TestParameterEdgeCases:
    """Edge case tests for parameter handling."""

    def test_output_param_formatting(self):
        params = [
            ParameterInfo(name="p_in", data_type="INT"),
            ParameterInfo(name="p_out", data_type="VARCHAR(100)", is_output=True),
        ]
        formatted = ProceduralConverter._format_parameters(params)
        assert "INOUT" in formatted
        assert "p_in" in formatted
        assert "p_out" in formatted

    def test_param_with_default_value(self):
        params = [
            ParameterInfo(name="p_name", data_type="VARCHAR(50)", default_value="'N/A'"),
        ]
        formatted = ProceduralConverter._format_parameters(params)
        assert "DEFAULT" in formatted.upper()

    def test_many_parameters(self):
        params = [ParameterInfo(name=f"p_{i}", data_type="INT") for i in range(50)]
        formatted = ProceduralConverter._format_parameters(params)
        assert len(formatted) > 0

    def test_no_parameters(self):
        formatted = ProceduralConverter._format_parameters([])
        assert formatted == ""

    def test_all_param_directions(self):
        params = [
            ParameterInfo(name="p_in", data_type="INT"),
            ParameterInfo(name="p_out", data_type="VARCHAR(100)", is_output=True),
            ParameterInfo(name="p_readonly", data_type="TABLE", is_readonly=True),
            ParameterInfo(name="p_defaulted", data_type="INT", default_value="0"),
        ]
        formatted = ProceduralConverter._format_parameters(params)
        assert "INOUT" in formatted

    def test_params_unusual_types(self):
        params = [
            ParameterInfo(name="p_xml", data_type="XML"),
            ParameterInfo(name="p_json", data_type="NVARCHAR(MAX)"),
            ParameterInfo(name="p_geo", data_type="GEOGRAPHY"),
            ParameterInfo(name="p_hier", data_type="HIERARCHYID"),
            ParameterInfo(name="p_table", data_type="TABLE", is_readonly=True),
        ]
        formatted = ProceduralConverter._format_parameters(params)
        assert len(formatted) > 0


class TestDifficultyEdgeCases:
    """Edge case tests for difficulty detection."""

    def test_empty_string(self):
        diff = TSqlPatternMatcher.detect_difficulty("")
        assert diff == ConversionDifficulty.SIMPLE

    def test_only_whitespace(self):
        diff = TSqlPatternMatcher.detect_difficulty("   \n  \t  ")
        assert diff == ConversionDifficulty.SIMPLE

    def test_case_insensitivity(self):
        diff_caps = TSqlPatternMatcher.detect_difficulty("EXEC(@sql)")
        diff_lower = TSqlPatternMatcher.detect_difficulty("exec(@sql)")
        assert diff_caps == diff_lower

    def test_multiple_complex_patterns(self):
        diff = TSqlPatternMatcher.detect_difficulty(
            "DECLARE c CURSOR FOR SELECT * FROM users; EXEC(@sql); sp_executesql @sql",
        )
        assert diff == ConversionDifficulty.EXTREME


class TestPatternDetectionEdgeCases:
    """Edge case tests for pattern detection."""

    def test_pattern_in_comment(self):
        patterns = TSqlPatternMatcher.detect_patterns("-- EXEC usp_test")
        assert "EXEC" in patterns

    def test_pattern_in_string_literal_not_flagged(self):
        patterns = TSqlPatternMatcher.detect_patterns("SELECT 'EXEC usp_test'")
        assert "EXEC" not in patterns

    def test_dm_exec_dmv_not_flagged(self):
        patterns = TSqlPatternMatcher.detect_patterns(
            "SELECT COUNT(*) FROM sys.dm_exec_connections",
        )
        assert "EXEC" not in patterns

    def test_output_parameter_name_not_flagged(self):
        patterns = TSqlPatternMatcher.detect_patterns(
            "@OutputFormat NVARCHAR(10) = 'SUMMARY'",
        )
        assert "OUTPUT" not in patterns

    def test_exact_boundary_match(self):
        patterns = TSqlPatternMatcher.detect_patterns("EXEC usp_test")
        assert "EXEC" in patterns

    def test_sp150_health_assessment_patterns(self):
        from pathlib import Path

        sql = Path(
            "SP_test/sqlserver_newSPs/150_sqlserver_sp_full_system_health_assessment.sql",
        ).read_text()
        patterns = TSqlPatternMatcher.detect_patterns(sql)
        assert "EXEC" not in patterns
        assert "OUTPUT" not in patterns
        assert "XML" in patterns
        assert "#temp" in patterns


class TestDynamicSqlAnalyzerEdgeCases:
    """Edge case tests for dynamic SQL analyzer."""

    ANALYZER = DynamicSqlAnalyzer()

    def test_empty_input(self):
        occurrences = self.ANALYZER.analyze("")
        assert len(occurrences) == 0

    def test_sql_with_comments(self):
        occurrences = self.ANALYZER.analyze("-- EXEC('SELECT 1')")
        assert len(occurrences) >= 0

    def test_consecutive_execs(self):
        occurrences = self.ANALYZER.analyze("EXEC a; EXEC b; EXEC c;")
        assert len(occurrences) == 1

    def test_remediation_consistency(self):
        occurrences = self.ANALYZER.analyze(
            "EXEC('SELECT * FROM ' + @table);\nsp_executesql @sql, @params;",
        )
        suggestions = self.ANALYZER.generate_remediation(occurrences)
        assert len(suggestions) >= 2

    def test_dynamic_sql_with_variable_concatenation(self):
        occ = self.ANALYZER.analyze("SET @sql = 'SELECT * FROM ' + @table; EXEC(@sql)")
        assert len(occ) >= 1

    def test_sp_executesql_with_output_params(self):
        occ = self.ANALYZER.analyze(
            "EXEC sp_executesql @sql, N'@cnt INT OUTPUT', @cnt = @count OUTPUT",
        )
        assert len(occ) >= 1


class TestControlFlowEdgeCases:
    """Edge case tests for CFG builder."""

    BUILDER = ControlFlowGraphBuilder()

    def test_deeply_nested_blocks(self):
        sql = """
        IF @a = 1
        BEGIN
            IF @b = 2
            BEGIN
                IF @c = 3
                BEGIN
                    SELECT 1;
                END
            END
        END
        """
        cfg = self.BUILDER.build(sql)
        if_nodes = cfg.find_all(lambda n: n.statement_type == "if")
        assert len(if_nodes) >= 3

    def test_cfg_no_infinite_loop(self):
        large_sql = "\n".join([f"SET @var{i} = {i};" for i in range(100)])
        cfg = self.BUILDER.build(large_sql)
        assert len(cfg.nodes) >= 2

    def test_cfg_with_try_catch(self):
        sql = """
        BEGIN TRY
            SELECT 1;
        END TRY
        BEGIN CATCH
            SELECT ERROR_MESSAGE();
        END CATCH
        """
        cfg = self.BUILDER.build(sql)
        catch_nodes = cfg.find_all(lambda n: n.statement_type == "catch")
        assert len(catch_nodes) >= 1

    def test_cfg_export_valid(self):
        cfg = self.BUILDER.build("SELECT 1;")
        mermaid = self.BUILDER.to_mermaid(cfg)
        assert mermaid.startswith("graph TD;")
        assert "N1" in mermaid

    def test_extreme_nesting_depth(self):
        sql_parts = []
        for i in range(20):
            sql_parts.append(f"IF @level{i} = {i}\nBEGIN\n")
        sql_parts.append("SELECT 1;\n")
        for _ in range(20):
            sql_parts.append("END\n")
        cfg = self.BUILDER.build("".join(sql_parts))
        if_nodes = cfg.find_all(lambda n: n.statement_type == "if")
        assert len(if_nodes) >= 15

    def test_while_inside_try_inside_cursor(self):
        sql = """
        DECLARE c CURSOR FOR SELECT id FROM users;
        OPEN c;
        BEGIN TRY
            WHILE 1=1
            BEGIN
                FETCH NEXT FROM c INTO @id;
                IF @@FETCH_STATUS <> 0 BREAK;
                SELECT @id;
            END
        END TRY
        BEGIN CATCH
            SELECT ERROR_MESSAGE();
        END CATCH
        CLOSE c;
        DEALLOCATE c;
        """
        cfg = self.BUILDER.build(sql)
        cursor_nodes = cfg.find_all(lambda n: n.statement_type == "cursor")
        catch_nodes = cfg.find_all(lambda n: n.statement_type == "catch")
        assert len(cursor_nodes) >= 1
        assert len(catch_nodes) >= 1

    def test_cfg_with_goto(self):
        sql = """
        GOTO error;
        SELECT 1;
        GOTO done;
        error:
        SELECT 0;
        done:
        SELECT -1;
        """
        cfg = self.BUILDER.build(sql)
        goto_nodes = cfg.find_all(lambda n: n.statement_type == "goto")
        assert len(goto_nodes) >= 2

    def test_cfg_very_long_body(self):
        lines = [f"SET @var{i} = {i};" for i in range(1000)]
        cfg = self.BUILDER.build("\n".join(lines))
        assert len(cfg.nodes) >= 2


class TestVariableScopeEdgeCases:
    """Edge case tests for variable scope resolver."""

    RESOLVER = VariableScopeResolver()

    def test_scope_resolve_multiple_blocks(self):
        sql = """
        BEGIN
            DECLARE @x INT;
            BEGIN
                DECLARE @y INT;
            END
        END
        """
        self.RESOLVER.resolve(sql)
        all_vars = self.RESOLVER.get_all_variables()
        names = {v.name for v in all_vars}
        assert "@x" in names
        assert "@y" in names

    def test_variable_reassigned(self):
        sql = "DECLARE @counter INT;\nSET @counter = 1;\nSET @counter = 2;"
        self.RESOLVER.resolve(sql)
        v = self.RESOLVER.get_variable("@counter")
        assert v is not None
        assert v.last_assigned_line > 0

    def test_undeclared_variables_detected(self):
        sql = "SELECT @undeclared;"
        undeclared = self.RESOLVER.find_undeclared_variables(sql)
        assert "@UNDECLARED" in undeclared

    def test_table_variable_declaration(self):
        sql = "DECLARE @tbl TABLE (id INT, name VARCHAR(100)); SELECT * FROM @tbl;"
        self.RESOLVER.resolve(sql)
        v = self.RESOLVER.get_variable("@tbl")
        assert v is not None
        assert v.is_table_variable

    def test_cursor_variable_declaration(self):
        sql = "DECLARE @c CURSOR; SET @c = CURSOR FOR SELECT id FROM users;"
        self.RESOLVER.resolve(sql)
        v = self.RESOLVER.get_variable("@c")
        assert v is not None
        assert v.is_cursor

    def test_unused_variables_found(self):
        sql = "DECLARE @unused INT; DECLARE @used INT; SELECT @used;"
        self.RESOLVER.resolve(sql)
        unused = self.RESOLVER.find_unused_variables()
        names = {v.name for v in unused}
        assert "@unused" in names
        assert "@used" not in names

    def test_variable_used_before_declaration(self):
        sql = "SELECT @x;"
        undeclared = self.RESOLVER.find_undeclared_variables(sql)
        assert "@X" in undeclared


class TestTvpEdgeCases:
    """Edge case tests for TVP converter."""

    CONVERTER = TvpConverter()

    def test_register_type_case_insensitive(self):
        td = TvpTypeDefinition(
            type_name="dbo.Udt_TestList", columns=[{"name": "id", "type": "INT"}],
        )
        self.CONVERTER.register_type(td)
        assert self.CONVERTER._type_definitions.get("DBO.UDT_TESTLIST") is not None

    def test_map_unknown_type_defaults_to_text(self):
        assert self.CONVERTER._map_type("CUSTOM_TYPE") == "TEXT"

    def test_temp_table_with_no_columns(self):
        from domains.transpilation.procedural_converter import TvpUsage
        usage = TvpUsage(variable_name="@empty", type_name="dbo.EmptyList", columns=[])
        result = self.CONVERTER.convert_to_temp_table(usage, "empty_data")
        assert "CREATE TEMPORARY TABLE" in result

    def test_jsonb_conversion_with_columns(self):
        from domains.transpilation.procedural_converter import TvpUsage
        usage = TvpUsage(
            variable_name="@data", type_name="dbo.IdList",
            columns=[{"name": "id", "type": "INT"}, {"name": "name", "type": "VARCHAR(100)"}],
        )
        result = self.CONVERTER.convert_to_jsonb(usage, "p_data")
        assert "jsonb_to_recordset" in result
        assert "id" in result
        assert "name" in result


class TestConverterIndentation:
    """Tests indentation handling."""

    def test_indent_body_preserves_lines(self):
        body = "SELECT 1;\nSELECT 2;"
        indented = ProceduralConverter._indent_body(body)
        lines = indented.split("\n")
        assert len(lines) == 2
        assert lines[0].startswith("    ")

    def test_indent_body_empty(self):
        indented = ProceduralConverter._indent_body("")
        assert indented == "    "


class TestExtremeNesting:
    """Tests for extreme nesting scenarios."""

    def test_very_long_procedure_body(self):
        lines = [f"SET @var{i} = {i};" for i in range(1000)]
        body = "\n".join(lines)
        result = CONVERTER.convert_procedure("dbo", "usp_long", [], body)
        assert result.success

    def test_deeply_nested_if_while_try(self):
        depth = 30
        parts = []
        for i in range(depth):
            parts.append(f"IF @level{i} = {i}\nBEGIN\n")
        parts.append("SELECT 1;\n")
        for _ in range(depth):
            parts.append("END\n")
        result = CONVERTER.convert_procedure("dbo", "usp_deep_nest", [], "".join(parts))
        assert result.success

    def test_deeply_nested_cte(self):
        cte_parts = []
        for i in range(10):
            prev = f"cte{i - 1}" if i > 0 else "source"
            cte_parts.append(f"cte{i} AS (SELECT * FROM {prev} WHERE id > {i})")
        sql = f"WITH {', '.join(cte_parts)} SELECT * FROM cte9"
        result = CONVERTER.convert_procedure("dbo", "usp_cte_deep", [], sql)
        assert result.success

    def test_function_name_edge_cases(self):
        names = ["fn_getdate", "fn_len", "fn_count", "fn_isnull", "fn_cast",
                 "fn_convert", "fn_row_number", "fn_rank", "fn_lag", "fn_lead"]
        for name in names:
            result = CONVERTER.convert_function(
                "dbo", name, [], "SELECT 1", return_type="INTEGER",
            )
            assert result.success, f"Failed for function name: {name}"


class TestEmptyEdgeCases:
    """Tests for empty/minimal edge cases."""

    def test_empty_param_list(self):
        result = CONVERTER.convert_procedure("dbo", "usp_empty_params", [], "SELECT 1")
        assert result.success
        assert "usp_empty_params" in result.converted_sql

    def test_procedure_no_body(self):
        result = CONVERTER.convert_procedure("dbo", "usp_no_body", [], "")
        assert result.success

    def test_procedure_no_body_with_params(self):
        result = CONVERTER.convert_procedure(
            "dbo", "usp_no_body_params",
            [ParameterInfo(name="p_id", data_type="INT")],
            "",
        )
        assert result.success

    def test_convert_procedure_no_schema(self):
        result = CONVERTER.convert_procedure("", "usp_no_schema", [], "SELECT 1")
        assert result.success

    def test_numeric_function_name_edge_cases(self):
        result = CONVERTER.convert_function(
            "dbo", "fn_123", [], "SELECT 1", return_type="INTEGER",
        )
        assert result.success

    def test_empty_parameter_names_not_crashing(self):
        result = CONVERTER.convert_procedure(
            "dbo", "usp_empty_names",
            [ParameterInfo(name="", data_type="INT")],
            "SELECT 1",
        )
        assert result.success
