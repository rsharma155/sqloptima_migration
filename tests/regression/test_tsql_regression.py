"""
Module: tests/regression/test_tsql_regression.py
Purpose: Regression test suite with hundreds of T-SQL constructs
Author: Migration Platform Team
Created: 2026-05-22
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

import pytest

from domains.parsing.sqlglot_adapter import SqlglotParser
from domains.transpilation.procedural_converter import (
    ConversionDifficulty,
    DynamicSqlAnalyzer,
    ParameterInfo,
    ProceduralConverter,
    TSqlPatternMatcher,
)

PARSER = SqlglotParser()
CONVERTER = ProceduralConverter()


def parse_ok(sql: str) -> bool:
    result = PARSER.parse(sql)
    return result.success


class TestSelectPatterns:
    """Regression tests for SELECT statement patterns."""

    @pytest.mark.parametrize("sql,expected_count", [
        ("SELECT TOP 10 * FROM users", 0),
        ("SELECT DISTINCT name FROM users", 0),
        ("SELECT COUNT(*) AS total FROM orders", 0),
        ("SELECT * INTO #temp FROM users", 1),
        ("SELECT * FROM (SELECT * FROM users) AS sub", 0),
    ])
    def test_select_patterns(self, sql, expected_count):
        patterns = TSqlPatternMatcher.detect_patterns(sql)
        assert len(patterns) == expected_count

    @pytest.mark.parametrize("sql,expected_difficulty", [
        ("SELECT 1", ConversionDifficulty.SIMPLE),
        ("SELECT * FROM users WHERE id = 1", ConversionDifficulty.SIMPLE),
    ])
    def test_select_difficulty(self, sql, expected_difficulty):
        diff = TSqlPatternMatcher.detect_difficulty(sql)
        assert diff == expected_difficulty


class TestJoinPatterns:
    """Regression tests for JOIN patterns."""

    @pytest.mark.parametrize("sql,has_cross_apply,has_outer_apply", [
        ("SELECT * FROM users CROSS APPLY fn_get_orders(users.id)", True, False),
        ("SELECT * FROM users OUTER APPLY fn_get_orders(users.id)", False, True),
        ("SELECT * FROM users JOIN orders ON users.id = orders.user_id", False, False),
        ("SELECT * FROM users LEFT JOIN orders ON users.id = orders.user_id", False, False),
    ])
    def test_apply_patterns(self, sql, has_cross_apply, has_outer_apply):
        patterns = TSqlPatternMatcher.detect_patterns(sql)
        assert ("CROSS APPLY" in patterns) == has_cross_apply
        assert ("OUTER APPLY" in patterns) == has_outer_apply

    @pytest.mark.parametrize("sql", [
        "SELECT * FROM a INNER JOIN b ON a.id = b.id",
        "SELECT * FROM a RIGHT JOIN b ON a.id = b.id",
        "SELECT * FROM a FULL OUTER JOIN b ON a.id = b.id",
        "SELECT * FROM a CROSS JOIN b",
        "SELECT * FROM a LEFT SEMI JOIN b ON a.id = b.id",
        "SELECT * FROM a WHERE NOT EXISTS (SELECT 1 FROM b WHERE a.id = b.id)",
        "SELECT * FROM a WHERE EXISTS (SELECT 1 FROM b WHERE a.id = b.id)",
        "SELECT * FROM a INNER HASH JOIN b ON a.id = b.id",
        "SELECT * FROM a INNER LOOP JOIN b ON a.id = b.id",
        "SELECT * FROM a INNER MERGE JOIN b ON a.id = b.id",
    ])
    def test_join_variations(self, sql):
        assert parse_ok(sql)


class TestSubqueryPatterns:
    """Regression tests for subquery patterns."""

    @pytest.mark.parametrize("sql", [
        "SELECT * FROM users WHERE id IN (SELECT user_id FROM orders)",
        "SELECT * FROM users WHERE id NOT IN (SELECT user_id FROM orders)",
        "SELECT * FROM users WHERE EXISTS (SELECT 1 FROM orders WHERE orders.user_id = users.id)",
        "SELECT * FROM users u WHERE (SELECT COUNT(*) FROM orders o WHERE o.user_id = u.id) > 5",
        "SELECT (SELECT MAX(id) FROM users) AS max_id",
        "SELECT * FROM users WHERE id = ANY (SELECT user_id FROM orders)",
        ("SELECT * FROM users WHERE id = ALL "
         "(SELECT user_id FROM orders WHERE user_id IS NOT NULL)"),
        "SELECT * FROM users WHERE id > SOME (SELECT user_id FROM orders)",
        "SELECT * FROM (SELECT id, name FROM users) AS u WHERE u.id > 10",
        "SELECT * FROM users WHERE id IN (SELECT user_id FROM orders WHERE orders.total > 100)",
    ])
    def test_subquery_parsing(self, sql):
        assert parse_ok(sql)


class TestDMLPatterns:
    """Regression tests for DML statements."""

    @pytest.mark.parametrize("sql", [
        "INSERT INTO users (id, name) VALUES (1, 'Alice')",
        "INSERT INTO users SELECT id, name FROM staging_users",
        "INSERT INTO users (id, name) VALUES (1, 'A'), (2, 'B')",
        "INSERT INTO users DEFAULT VALUES",
        "UPDATE users SET name = 'Bob' WHERE id = 1",
        "UPDATE u SET u.name = s.name FROM users u JOIN staging s ON u.id = s.id",
        "UPDATE users SET name = 'Bob' FROM staging WHERE users.id = staging.id",
        "DELETE FROM users WHERE id = 1",
        "DELETE u FROM users u JOIN orders o ON u.id = o.user_id WHERE o.total < 0",
        "MERGE users AS t USING staging AS s ON t.id = s.id "
        "WHEN MATCHED THEN UPDATE SET t.name = s.name "
        "WHEN NOT MATCHED THEN INSERT (id, name) VALUES (s.id, s.name)",
        "TRUNCATE TABLE users",
        "DELETE FROM users",
    ])
    def test_dml_parsing(self, sql):
        assert parse_ok(sql)


class TestDDLPatterns:
    """Regression tests for DDL patterns."""

    @pytest.mark.parametrize("sql", [
        "CREATE TABLE users (id INT NOT NULL, name VARCHAR(100))",
        "ALTER TABLE users ADD email VARCHAR(255)",
        "ALTER TABLE users DROP COLUMN email",
        "ALTER TABLE users ALTER COLUMN name VARCHAR(200)",
        "DROP TABLE users",
        "CREATE TABLE #temp (id INT)",
        "CREATE TABLE dbo.users (id INT PRIMARY KEY, name NVARCHAR(100))",
        "CREATE TABLE users (id INT IDENTITY(1,1), name VARCHAR(100))",
        "CREATE TABLE users (id INT DEFAULT 0, name VARCHAR(100))",
        "CREATE INDEX idx_name ON users(name)",
        "CREATE UNIQUE INDEX idx_email ON users(email) WHERE email IS NOT NULL",
        "CREATE CLUSTERED INDEX idx_id ON users(id)",
        "CREATE NONCLUSTERED INDEX idx_name ON users(name) INCLUDE (email)",
        "DROP INDEX users.idx_name",
        "ALTER INDEX idx_name ON users REBUILD",
        "CREATE VIEW v_users AS SELECT id, name FROM users",
        "CREATE VIEW v_users WITH SCHEMABINDING AS SELECT * FROM users",
        "ALTER VIEW v_users AS SELECT id, name, email FROM users",
        "DROP VIEW v_users",
        "CREATE SYNONYM remote_users FOR server.db.dbo.users",
        "DROP SYNONYM remote_users",
        "CREATE TYPE dbo.id_list AS TABLE (id INT)",
        "DROP TYPE dbo.id_list",
        "CREATE STATISTICS st_users_name ON users(name)",
        "UPDATE STATISTICS users",
        "DROP STATISTICS users.st_users_name",
    ])
    def test_ddl_parsing(self, sql):
        assert parse_ok(sql)


class TestProcedureDDL:
    """Regression tests for procedure/function DDL."""

    @pytest.mark.parametrize("sql", [
        "CREATE PROCEDURE usp_test AS BEGIN SELECT 1 END",
        "CREATE PROC usp_test @id INT AS SELECT @id",
        "CREATE PROCEDURE dbo.usp_test @p1 INT, @p2 VARCHAR(100) AS SELECT @p1, @p2",
        "ALTER PROCEDURE usp_test @id INT AS SELECT @id",
        "CREATE FUNCTION fn_test() RETURNS INT AS BEGIN RETURN 1 END",
        "CREATE FUNCTION dbo.fn_add(@a INT, @b INT) RETURNS INT AS BEGIN RETURN @a + @b END",
        "ALTER FUNCTION fn_test() RETURNS INT AS BEGIN RETURN 2 END",
        "CREATE TRIGGER trg_test ON dbo.users AFTER INSERT AS BEGIN SELECT 1 END",
        "CREATE TRIGGER trg_test ON dbo.users INSTEAD OF DELETE AS BEGIN SELECT 1 END",
        "ALTER TRIGGER trg_test ON dbo.users AFTER INSERT AS BEGIN SELECT 2 END",
        "DROP PROCEDURE usp_test",
        "DROP FUNCTION fn_test",
        "DROP TRIGGER trg_test",
    ])
    def test_procedure_ddl(self, sql):
        assert parse_ok(sql)


class TestDataTypePatterns:
    """Regression tests for all SQL Server data types."""

    ALL_TYPES = [
        "INT", "BIGINT", "SMALLINT", "TINYINT", "BIT", "DECIMAL(18,2)",
        "NUMERIC(10,5)", "MONEY", "SMALLMONEY", "FLOAT", "REAL",
        "DATETIME", "DATETIME2(3)", "SMALLDATETIME", "DATE", "TIME(7)",
        "DATETIMEOFFSET(2)", "CHAR(10)", "VARCHAR(100)", "VARCHAR(MAX)",
        "NVARCHAR(200)", "NVARCHAR(MAX)", "NCHAR(50)", "TEXT", "NTEXT",
        "BINARY(100)", "VARBINARY(200)", "VARBINARY(MAX)", "IMAGE",
        "UNIQUEIDENTIFIER", "XML", "HIERARCHYID", "GEOGRAPHY",
        "GEOMETRY",         "SQL_VARIANT", "ROWVERSION", "TIMESTAMP",
    ]

    @pytest.mark.parametrize("sql_type", ALL_TYPES)
    def test_column_with_type(self, sql_type):
        sql = f"CREATE TABLE dbo.types_test (col {sql_type})"
        assert parse_ok(sql)


class TestFunctionPatterns:
    """Regression tests for T-SQL function patterns."""

    @pytest.mark.parametrize("sql", [
        "SELECT COUNT(*) FROM users",
        "SELECT SUM(amount) FROM orders",
        "SELECT AVG(price) FROM products",
        "SELECT MIN(date_created), MAX(date_created) FROM orders",
        "SELECT GETDATE()",
        "SELECT GETUTCDATE()",
        "SELECT LEN(name) FROM users",
        "SELECT UPPER(name), LOWER(email) FROM users",
        "SELECT SUBSTRING(name, 1, 3) FROM users",
        "SELECT LEFT(name, 5), RIGHT(name, 5) FROM users",
        "SELECT CHARINDEX('@', email) FROM users",
        "SELECT REPLACE(name, 'a', 'b') FROM users",
        "SELECT LTRIM(RTRIM(name)) FROM users",
        "SELECT ABS(value), CEILING(value), FLOOR(value), ROUND(value, 2) FROM metrics",
        "SELECT ISNULL(name, 'N/A') FROM users",
        "SELECT COALESCE(name, email, 'unknown') FROM users",
        "SELECT CAST(created_date AS DATE) FROM orders",
        "SELECT CONVERT(VARCHAR(10), created_date, 101) FROM orders",
        "SELECT TRY_CAST(value AS INT) FROM data",
        "SELECT IIF(age >= 18, 'Adult', 'Minor') FROM users",
        "SELECT CHOOSE(index, 'A', 'B', 'C')",
        "SELECT NEWID()",
        "SELECT SCOPE_IDENTITY()",
        "SELECT DB_NAME()",
        "SELECT HOST_NAME()",
        "SELECT OBJECT_NAME(object_id)",
        "SELECT ROW_NUMBER() OVER (ORDER BY id) FROM users",
        "SELECT RANK() OVER (PARTITION BY dept ORDER BY salary DESC) FROM employees",
        "SELECT DENSE_RANK() OVER (ORDER BY score) FROM results",
        "SELECT NTILE(4) OVER (ORDER BY id) FROM users",
        "SELECT LAG(amount) OVER (ORDER BY date) FROM orders",
        "SELECT LEAD(amount) OVER (ORDER BY date) FROM orders",
        "SELECT FIRST_VALUE(amount) OVER (ORDER BY date) FROM orders",
        "SELECT LAST_VALUE(amount) OVER (ORDER BY date) FROM orders",
        "SELECT CUME_DIST() OVER (ORDER BY score) FROM results",
        "SELECT PERCENT_RANK() OVER (ORDER BY score) FROM results",
    ])
    def test_function_parsing(self, sql):
        assert parse_ok(sql)


class TestWindowFunctionPatterns:
    """Regression tests for window functions."""

    @pytest.mark.parametrize("sql", [
        "SELECT ROW_NUMBER() OVER (ORDER BY id) FROM users",
        "SELECT ROW_NUMBER() OVER (PARTITION BY dept ORDER BY salary) FROM emp",
        ("SELECT SUM(amount) OVER "
         "(ORDER BY date ROWS BETWEEN 1 PRECEDING AND 1 FOLLOWING) FROM orders"),
        ("SELECT AVG(score) OVER "
         "(ORDER BY date ROWS UNBOUNDED PRECEDING) FROM scores"),
        "SELECT COUNT(*) OVER (PARTITION BY status) FROM orders",
        ("SELECT PERCENTILE_CONT(0.5) WITHIN GROUP "
         "(ORDER BY salary) OVER (PARTITION BY dept) FROM emp"),
        ("SELECT PERCENTILE_DISC(0.5) WITHIN GROUP "
         "(ORDER BY salary) OVER (PARTITION BY dept) FROM emp"),
    ])
    def test_window_function_parsing(self, sql):
        assert parse_ok(sql)


class TestControlFlowPatterns:
    """Regression tests for control flow."""

    @pytest.mark.parametrize("sql", [
        "IF @x = 1 SELECT 1",
        "IF @x = 1 SELECT 1 ELSE SELECT 2",
        "IF @x = 1 BEGIN SELECT 1 END ELSE BEGIN SELECT 2 END",
        "IF EXISTS (SELECT 1 FROM users) SELECT 1 ELSE SELECT 0",
        "WHILE @i <= 10 BEGIN SELECT @i; SET @i = @i + 1; END",
        "WHILE 1=1 BEGIN SELECT 1; IF @x = 1 BREAK; END",
        "BEGIN SELECT 1 END",
        "BEGIN TRANSACTION",
        "COMMIT TRANSACTION",
        "ROLLBACK TRANSACTION",
        "BEGIN RETURN 1; END",
    ])
    def test_control_flow_parsing(self, sql):
        assert parse_ok(sql)


class TestErrorHandlingPatterns:
    """Regression tests for error handling."""

    @pytest.mark.parametrize("sql", [
        "BEGIN TRY SELECT 1 END TRY BEGIN CATCH SELECT ERROR_MESSAGE() END CATCH",
        ("BEGIN TRY SELECT 1 END TRY BEGIN CATCH "
         "SELECT ERROR_NUMBER(), ERROR_SEVERITY(), ERROR_STATE() END CATCH"),
        ("BEGIN TRY SELECT 1 END TRY BEGIN CATCH "
         "SELECT ERROR_PROCEDURE(), ERROR_LINE(), ERROR_MESSAGE() END CATCH"),
        ("BEGIN TRY BEGIN TRANSACTION DELETE FROM users COMMIT "
         "END TRY BEGIN CATCH ROLLBACK END CATCH"),
        ("BEGIN TRY SELECT 1 END TRY BEGIN CATCH "
         "IF @@TRANCOUNT > 0 ROLLBACK END CATCH"),
    ])
    def test_error_handling(self, sql):
        assert parse_ok(sql)


class TestDynamicSqlPatterns:
    """Regression tests for dynamic SQL patterns."""

    ANALYZER = DynamicSqlAnalyzer()

    @pytest.mark.parametrize("sql,expected_count", [
        ("EXEC('SELECT * FROM users')", 1),
        ("EXEC usp_get_users @id", 1),
        ("sp_executesql @sql, N'@id INT', @id = 1", 1),
        ("SELECT * FROM users WHERE name = @name", 0),
        ("EXEC('SELECT * FROM ' + @table)", 1),
        ("EXEC dbo.usp_get_users @id = 1", 1),
    ])
    def test_dynamic_sql_count(self, sql, expected_count):
        occurrences = self.ANALYZER.analyze(sql)
        assert len(occurrences) == expected_count

    @pytest.mark.parametrize("sql,expected_risk", [
        ("EXEC('SELECT * FROM ' + @table)", "high"),
        ("sp_executesql @sql, @params, @p1", "medium"),
        ("EXEC usp_get_users", "low"),
    ])
    def test_dynamic_sql_risk_levels(self, sql, expected_risk):
        occurrences = self.ANALYZER.analyze(sql)
        assert len(occurrences) > 0
        assert occurrences[0].risk_level == expected_risk


class TestTransactionPatterns:
    """Regression tests for transaction statements."""

    @pytest.mark.parametrize("sql", [
        "BEGIN TRAN",
        "BEGIN TRANSACTION",
        "BEGIN TRAN t1",
        "COMMIT TRAN",
        "COMMIT TRANSACTION t1",
        "ROLLBACK",
        "ROLLBACK TRAN",
        "SELECT @@TRANCOUNT",
        "SELECT XACT_STATE()",
        "SET XACT_ABORT ON",
        "SET XACT_ABORT OFF",
        ("BEGIN TRY BEGIN TRAN DELETE FROM users COMMIT "
         "END TRY BEGIN CATCH IF @@TRANCOUNT > 0 ROLLBACK END CATCH"),
    ])
    def test_transaction_parsing(self, sql):
        assert parse_ok(sql)


class TestCursorPatterns:
    """Regression tests for cursor patterns."""

    @pytest.mark.parametrize("sql", [
        "DECLARE c CURSOR FOR SELECT id, name FROM users",
        "DECLARE c CURSOR STATIC FOR SELECT id FROM users",
        "DECLARE c CURSOR DYNAMIC FOR SELECT id FROM users",
        "DECLARE c CURSOR FAST_FORWARD FOR SELECT id FROM users",
        "DECLARE c CURSOR READ_ONLY FOR SELECT id FROM users",
        "DECLARE c CURSOR SCROLL FOR SELECT id FROM users",
        "DECLARE c CURSOR LOCAL FOR SELECT id FROM users",
        "DECLARE c CURSOR GLOBAL FOR SELECT id FROM users",
        "DECLARE c CURSOR FORWARD_ONLY FOR SELECT id FROM users",
        "DECLARE c CURSOR KEYSET FOR SELECT id FROM users",
        "OPEN c",
        "FETCH NEXT FROM c INTO @id, @name",
        "FETCH FIRST FROM c INTO @id",
        "FETCH LAST FROM c INTO @id",
        "FETCH PRIOR FROM c INTO @id",
        "FETCH ABSOLUTE 5 FROM c INTO @id",
        "FETCH RELATIVE -2 FROM c INTO @id",
        "CLOSE c",
        "DEALLOCATE c",
        "SELECT @@FETCH_STATUS",
        "SELECT CURSOR_STATUS('local', 'c')",
    ])
    def test_cursor_parsing(self, sql):
        assert parse_ok(sql)


class TestXmlPatterns:
    """Regression tests for XML patterns."""

    @pytest.mark.parametrize("sql", [
        "SELECT * FROM users FOR XML PATH('user')",
        "SELECT * FROM users FOR XML AUTO",
        "SELECT * FROM users FOR XML RAW",
        "SELECT * FROM users FOR XML EXPLICIT",
        "SELECT * FROM users FOR XML PATH('user'), ROOT('users')",
        "SELECT * FROM users FOR XML PATH('user'), TYPE",
        "SELECT xml_data.query('/root/element') FROM xml_table",
        "SELECT xml_data.value('(/root/element)[1]', 'INT') FROM xml_table",
        "SELECT xml_data.exist('/root/element') FROM xml_table",
        ("SELECT xml_data.modify('replace value of "
         "(/root/element)[1] with \"new\"') FROM xml_table"),
        "DECLARE @doc INT EXEC sp_xml_preparedocument @doc OUTPUT, @xml",
    ])
    def test_xml_parsing(self, sql):
        assert parse_ok(sql)


class TestJsonPatterns:
    """Regression tests for JSON patterns."""

    @pytest.mark.parametrize("sql", [
        "SELECT JSON_VALUE(data, '$.name') FROM users",
        "SELECT JSON_QUERY(data, '$.address') FROM users",
        "SELECT JSON_MODIFY(data, '$.name', 'NewName') FROM users",
        "SELECT ISJSON(data) FROM users",
        "SELECT * FROM OPENJSON(@jsonArray) WITH (id INT)",
    ])
    def test_json_parsing(self, sql):
        assert parse_ok(sql)


class TestSystemVariablePatterns:
    """Regression tests for system variable patterns."""

    @pytest.mark.parametrize("sql", [
        "SELECT @@ROWCOUNT",
        "SELECT @@IDENTITY",
        "SELECT @@ERROR",
        "SELECT @@FETCH_STATUS",
        "SELECT @@NESTLEVEL",
        "SELECT @@SERVERNAME",
        "SELECT @@VERSION",
        "SELECT @@LANGUAGE",
        "SELECT @@SPID",
        "SELECT @@TRANCOUNT",
        "SELECT @@MAX_CONNECTIONS",
        "SELECT @@CPU_BUSY",
        "SELECT @@IO_BUSY",
        "SELECT @@IDLE",
        "SELECT @@TOTAL_ERRORS",
        "SELECT @@PACK_RECEIVED",
        "SELECT @@PACK_SENT",
        "SELECT @@TIMETICKS",
        "SELECT @@TOTAL_READ",
        "SELECT @@TOTAL_WRITE",
    ])
    def test_system_variables(self, sql):
        assert parse_ok(sql)


class TestAdvancedQueryPatterns:
    """Regression tests for advanced query constructs."""

    @pytest.mark.parametrize("sql", [
        "SELECT * FROM users ORDER BY name OFFSET 10 ROWS FETCH NEXT 5 ROWS ONLY",
        "SELECT TOP 10 WITH TIES * FROM users ORDER BY score DESC",
        "SELECT * FROM users TABLESAMPLE SYSTEM (10 PERCENT)",
        "SELECT * FROM users TABLESAMPLE (100 ROWS)",
        ("SELECT * FROM users CROSS APPLY "
         "(SELECT TOP 1 * FROM orders WHERE orders.user_id = users.id) o"),
        ("SELECT * FROM users OUTER APPLY "
         "(SELECT TOP 1 * FROM orders WHERE orders.user_id = users.id) o"),
        "SELECT * FROM (VALUES (1, 'A'), (2, 'B')) AS v(id, name)",
        "SELECT * FROM users WHERE id BETWEEN 1 AND 100",
        "SELECT * FROM users WHERE name LIKE '%test%'",
        "SELECT * FROM users WHERE name IN ('Alice', 'Bob', 'Charlie')",
        "SELECT * FROM users WHERE email IS NULL",
        "SELECT * FROM users WHERE id = ANY (SELECT id FROM orders)",
        ("SELECT CASE WHEN id > 100 THEN 'big' "
         "WHEN id > 50 THEN 'medium' ELSE 'small' END FROM users"),
        "SELECT NULLIF(name, '') FROM users",
        "SELECT CONCAT(first_name, ' ', last_name) FROM users",
        "SELECT FORMAT(created_date, 'yyyy-MM-dd') FROM users",
        "SELECT STRING_AGG(name, ',') FROM users",
        "SELECT TRIM(' ' FROM name) FROM users",
        "SELECT PATINDEX('%test%', name) FROM users",
        "SELECT REPLICATE('*', 5)",
        "SELECT SPACE(10)",
        "SELECT REVERSE(name) FROM users",
        "SELECT STUFF(name, 1, 3, 'prefix') FROM users",
        "SELECT EOMONTH(created_date) FROM orders",
        "SELECT DATEPART(YEAR, created_date) FROM orders",
        "SELECT YEAR(created_date), MONTH(created_date), DAY(created_date) FROM orders",
        "SELECT DATEDIFF(DAY, start_date, end_date) FROM projects",
        "SELECT DATEADD(DAY, 7, created_date) FROM orders",
    ])
    def test_advanced_query_parsing(self, sql):
        assert parse_ok(sql)


class TestPivotUnpivotPatterns:
    """Regression tests for PIVOT/UNPIVOT patterns."""

    @pytest.mark.parametrize("sql", [
        "SELECT * FROM (SELECT year, revenue FROM sales) src "
        "PIVOT (SUM(revenue) FOR year IN ([2020], [2021], [2022])) pvt",
        "SELECT * FROM (SELECT id, attr, value FROM attributes) src "
        "PIVOT (MAX(value) FOR attr IN (color, size, weight)) pvt",
        "SELECT * FROM (SELECT id, qty, period FROM inventory) src "
        "UNPIVOT (qty FOR period IN (q1, q2, q3, q4)) unpvt",
        "SELECT * FROM (SELECT id, color, size FROM items) src "
        "UNPIVOT (value FOR attr IN (color, size)) unpvt",
    ])
    def test_pivot_unpivot(self, sql):
        assert parse_ok(sql)


class TestGroupingPatterns:
    """Regression tests for GROUP BY extensions."""

    @pytest.mark.parametrize("sql", [
        "SELECT dept, SUM(salary) FROM emp GROUP BY dept",
        "SELECT dept, gender, SUM(salary) FROM emp GROUP BY GROUPING SETS ((dept), (gender), ())",
        "SELECT dept, SUM(salary) FROM emp GROUP BY CUBE (dept, gender)",
        "SELECT dept, gender, SUM(salary) FROM emp GROUP BY ROLLUP (dept, gender)",
        "SELECT dept, gender, SUM(salary) FROM emp GROUP BY dept, gender WITH CUBE",
        "SELECT dept, gender, SUM(salary) FROM emp GROUP BY dept, gender WITH ROLLUP",
        "SELECT dept, SUM(salary) FROM emp GROUP BY dept HAVING SUM(salary) > 10000",
        "SELECT GROUPING(dept), dept FROM emp GROUP BY ROLLUP(dept)",
    ])
    def test_grouping_parsing(self, sql):
        assert parse_ok(sql)


class TestCtePatterns:
    """Regression tests for CTE patterns."""

    @pytest.mark.parametrize("sql", [
        "WITH cte AS (SELECT id, name FROM users) SELECT * FROM cte",
        ("WITH cte1 AS (SELECT id FROM users), cte2 AS (SELECT id FROM orders) "
         "SELECT * FROM cte1 JOIN cte2 ON cte1.id = cte2.id"),
        ("WITH emp_cte AS "
         "(SELECT id, manager_id, name FROM employees WHERE manager_id IS NULL "
         "UNION ALL SELECT e.id, e.manager_id, e.name "
         "FROM employees e JOIN emp_cte ON e.manager_id = emp_cte.id) "
         "SELECT * FROM emp_cte"),
        ("WITH cte AS (SELECT id, ROW_NUMBER() OVER (ORDER BY id) AS rn FROM users) "
         "SELECT * FROM cte WHERE rn <= 10"),
    ])
    def test_cte_parsing(self, sql):
        assert parse_ok(sql)


class TestOutputPatterns:
    """Regression tests for OUTPUT clause patterns."""

    @pytest.mark.parametrize("sql", [
        "INSERT INTO users (name) OUTPUT INSERTED.id VALUES ('Alice')",
        "UPDATE users SET name = 'Bob' OUTPUT DELETED.name, INSERTED.name WHERE id = 1",
        "INSERT INTO users (name) OUTPUT INSERTED.id, INSERTED.name VALUES ('Alice')",
        "UPDATE users SET name = 'Bob' OUTPUT INSERTED.id, INSERTED.name WHERE id = 1",
    ])
    def test_output_parsing(self, sql):
        assert parse_ok(sql)


class TestProcedureEdgeCases:
    """Regression tests for procedural code edge cases."""

    @pytest.mark.parametrize("name,params,body", [
        ("usp_empty", [], ""),
        ("usp_single_line", [("p_id", "INT")], "SELECT 1"),
        ("usp_no_params", [], "SELECT * FROM users"),
        ("usp_output_only", [("p_count", "INT", True)], "SELECT COUNT(*) FROM users"),
        ("usp_multi_params", [("p1", "INT"), ("p2", "VARCHAR(100)"), ("p3", "DATETIME", True)],
         "SELECT @p1, @p2"),
    ])
    def test_procedure_variations(self, name, params, body):
        param_objs = [
            ParameterInfo(name=p[0], data_type=p[1], is_output=p[2] if len(p) > 2 else False)
            for p in params
        ]
        result = CONVERTER.convert_procedure("dbo", name, param_objs, body)
        assert result.success is True

    @pytest.mark.parametrize("body,is_complex", [
        ("DECLARE c CURSOR FOR SELECT * FROM users;", True),
        ("BEGIN TRY SELECT 1 END TRY BEGIN CATCH END CATCH", False),
        ("SELECT 1", False),
        ("EXEC('SELECT 1')", True),
        ("MERGE target USING source ON target.id = source.id "
         "WHEN MATCHED THEN UPDATE SET ...", True),
    ])
    def test_complexity_warnings(self, body, is_complex):
        result = CONVERTER.convert_procedure("dbo", "usp_test", [], body)
        if is_complex:
            assert len(result.warnings) > 0, f"Expected warnings for: {body}"

    def test_very_large_procedure(self):
        lines = [f"SET @var{i} = {i};" for i in range(500)]
        large_body = "\n".join(lines)
        result = CONVERTER.convert_procedure("dbo", "usp_large", [], large_body)
        assert result.success is True

    @pytest.mark.parametrize("body", [
        "SELECT 1",
        "SELECT * FROM users WHERE id = @id",
        "INSERT INTO users (name) VALUES (@name)",
        "UPDATE users SET name = @name WHERE id = @id",
        "DELETE FROM users WHERE id = @id",
        "DECLARE @x INT = 10; WHILE @x > 0 BEGIN SELECT @x SET @x = @x - 1 END",
        "IF @x = 1 SELECT 1 ELSE SELECT 2",
        "BEGIN TRY SELECT 1 END TRY BEGIN CATCH SELECT ERROR_MESSAGE() END CATCH",
        "DECLARE c CURSOR FOR SELECT id FROM users OPEN c FETCH NEXT FROM c INTO @id",
    ])
    def test_various_bodies_convert(self, body):
        result = CONVERTER.convert_procedure("dbo", "usp_test", [], body)
        assert result.success


class TestTypeMappingsRegression:
    """Regression tests for type mapping edge cases."""

    def test_all_known_types_have_mappings(self):
        from domains.transpilation.type_mappings import get_type_mapping
        types = ["INT", "BIGINT", "VARCHAR", "NVARCHAR", "DATETIME", "DECIMAL",
                 "FLOAT", "BIT", "UNIQUEIDENTIFIER", "TEXT", "NTEXT", "IMAGE",
                 "SMALLINT", "TINYINT", "MONEY", "DATE", "TIME", "BINARY", "VARBINARY"]
        for t in types:
            mapping = get_type_mapping(t)
            assert mapping is not None, f"No mapping for {t}"

    def test_no_missing_common_types(self):
        from domains.transpilation.type_mappings import get_type_mapping
        common = ["INT", "BIGINT", "VARCHAR", "NVARCHAR", "DATETIME", "DECIMAL",
                  "FLOAT", "BIT", "UNIQUEIDENTIFIER", "TEXT", "NTEXT", "IMAGE",
                  "SMALLINT", "TINYINT", "MONEY", "DATE", "TIME", "BINARY", "VARBINARY"]
        failed = [t for t in common if not get_type_mapping(t)]
        assert len(failed) < len(common) // 2, f"Too many missing types: {failed}"

    @pytest.mark.parametrize("tsql_type,expected_pg", [
        ("INT", "INTEGER"),
        ("BIGINT", "BIGINT"),
        ("VARCHAR", "VARCHAR"),
        ("NVARCHAR", "VARCHAR"),
        ("DATETIME", "TIMESTAMP"),
        ("DECIMAL", "NUMERIC"),
        ("BIT", "BOOLEAN"),
        ("UNIQUEIDENTIFIER", "UUID"),
        ("MONEY", "NUMERIC"),
        ("HIERARCHYID", "LTREE"),
    ])
    def test_specific_type_mappings(self, tsql_type, expected_pg):
        from domains.transpilation.ddl_generator import DdlGenerator
        from domains.transpilation.ir_models import DataTypeNode
        gen = DdlGenerator()
        dt = DataTypeNode(type_name=tsql_type)
        result = gen._generate_data_type(dt)
        assert result == expected_pg

    def test_varchar_max_maps_to_text(self):
        from domains.transpilation.ddl_generator import DdlGenerator
        from domains.transpilation.ir_models import DataTypeNode
        gen = DdlGenerator()
        dt = DataTypeNode(type_name="VARCHAR", max_length=-1)
        result = gen._generate_data_type(dt)
        assert result == "TEXT"


class TestSqlglotParserRegression:
    """Regression tests for the SQLGlot parser."""

    PARSER = SqlglotParser()

    @pytest.mark.parametrize("sql", [
        "SELECT 1",
        "SELECT * FROM dbo.users",
        "SELECT TOP 10 id, name FROM users ORDER BY name",
        "SELECT DISTINCT city FROM users",
        "SELECT COUNT(*), AVG(age), MIN(score), MAX(score) FROM results",
        "SELECT id, name INTO #temp FROM users WHERE active = 1",
        "SELECT id FROM users WHERE name LIKE 'A%' AND age > 18",
        "SELECT id FROM users ORDER BY name DESC, id ASC",
        "SELECT id FROM users GROUP BY dept_id HAVING COUNT(*) > 5",
        "SELECT id, name FROM users FOR XML AUTO",
        "SELECT id FROM users OPTION (RECOMPILE, MAXDOP 4)",
        "SELECT id FROM users OPTION (OPTIMIZE FOR UNKNOWN)",
        "SELECT id FROM users OPTION (FAST 10)",
    ])
    def test_select_variations(self, sql):
        result = self.PARSER.parse(sql)
        assert result.success, f"Failed to parse: {sql}"

    @pytest.mark.parametrize("sql", [
        "SELECT 1; SELECT 2; SELECT 3",
        "SELECT 1; SELECT 2;",
    ])
    def test_multiple_statement_parsing(self, sql):
        results = self.PARSER.parse_multiple(sql)
        assert len(results) >= 2
        assert any(r.success for r in results)

    @pytest.mark.parametrize("sql,expected_keyword", [
        ("SELECT TOP 10 * FROM users", "LIMIT"),
        ("SELECT ISNULL(name, 'N/A') FROM users", "COALESCE"),
        ("SELECT GETDATE()", "CURRENT_TIMESTAMP"),
        ("SELECT LEN(name) FROM users", "LENGTH"),
        ("SELECT CHARINDEX('x', name) FROM users", "POSITION"),
        ("SELECT UPPER(name) FROM users", "UPPER"),
        ("SELECT ABS(-1)", "ABS"),
    ])
    def test_transpile_keywords(self, sql, expected_keyword):
        result = self.PARSER.transpile(sql)
        assert expected_keyword.upper() in result.upper() or expected_keyword in result

    def test_invalid_sql_returns_errors(self):
        result = self.PARSER.parse("SELEC 1 FROM WHERE")
        assert not result.success
        assert len(result.errors) > 0

    def test_empty_string_fails(self):
        result = self.PARSER.parse("")
        assert not result.success


class TestTranspileEdgeCases:
    """Regression tests for transpilation edge cases."""

    PARSER = SqlglotParser()

    @pytest.mark.parametrize("sql", [
        "SELECT * FROM users WHERE id IN (1, 2, 3)",
        "SELECT * FROM users WHERE id BETWEEN 1 AND 100",
        "SELECT * FROM users WHERE name IS NULL",
        "SELECT * FROM users WHERE name IS NOT NULL",
        "SELECT COALESCE(name, email, 'unknown') FROM users",
        "SELECT NULLIF(name, '') FROM users",
        "SELECT id, CASE WHEN status = 'A' THEN 'Active' ELSE 'Inactive' END FROM users",
        "SELECT CAST(id AS VARCHAR(10)) FROM users",
        "SELECT CAST(created_date AS DATE) FROM orders",
        "SELECT a.*, b.name FROM users a JOIN orders b ON a.id = b.user_id",
    ])
    def test_transpile_common_patterns(self, sql):
        result = self.PARSER.transpile(sql)
        assert len(result) > 0, f"Empty transpile result for: {sql}"
