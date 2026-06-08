-- ============================================================
-- Dynamic ORDER BY with Multiple Sort Levels and NULL Handling
-- ============================================================
CREATE PROCEDURE dbo.usp_DynamicSortQuery
    @SchemaName NVARCHAR(128) = 'dbo',
    @TableName NVARCHAR(128),
    @Columns NVARCHAR(MAX),
    @SortExpression NVARCHAR(MAX),
    @NullsPosition NVARCHAR(4) = 'LAST',
    @DistinctFlag BIT = 0,
    @WhereClause NVARCHAR(500) = NULL,
    @RowLimit INT = NULL
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @Sql NVARCHAR(MAX);
    DECLARE @FullTable NVARCHAR(256);
    DECLARE @SortClause NVARCHAR(MAX);
    DECLARE @NullHandling NVARCHAR(100);

    SET @FullTable = QUOTENAME(@SchemaName) + N'.' + QUOTENAME(@TableName);

    DECLARE @SortTable TABLE (
        SortOrder INT IDENTITY(1,1),
        ColumnName NVARCHAR(128),
        Direction NVARCHAR(4),
        NullHandling NVARCHAR(10)
    );

    INSERT INTO @SortTable (ColumnName, Direction, NullHandling)
    SELECT
        TRIM(PARSENAME(REPLACE(TRIM(value), ' ', '.'), 2)),
        CASE
            WHEN UPPER(TRIM(value)) LIKE '% DESC' THEN 'DESC'
            ELSE 'ASC'
        END,
        CASE
            WHEN UPPER(TRIM(value)) LIKE '% NULLS FIRST' THEN 'FIRST'
            WHEN UPPER(TRIM(value)) LIKE '% NULLS LAST' THEN 'LAST'
            ELSE @NullsPosition
        END
    FROM STRING_SPLIT(@SortExpression, ',');

    SELECT @SortClause = STRING_AGG(
        CASE
            WHEN NullHandling = 'FIRST' AND Direction = 'ASC'
                THEN 'CASE WHEN ' + QUOTENAME(ColumnName) + ' IS NULL THEN 0 ELSE 1 END ASC, ' + QUOTENAME(ColumnName) + ' ASC'
            WHEN NullHandling = 'FIRST' AND Direction = 'DESC'
                THEN 'CASE WHEN ' + QUOTENAME(ColumnName) + ' IS NULL THEN 0 ELSE 1 END ASC, ' + QUOTENAME(ColumnName) + ' DESC'
            WHEN NullHandling = 'LAST' AND Direction = 'ASC'
                THEN 'CASE WHEN ' + QUOTENAME(ColumnName) + ' IS NULL THEN 1 ELSE 0 END ASC, ' + QUOTENAME(ColumnName) + ' ASC'
            WHEN NullHandling = 'LAST' AND Direction = 'DESC'
                THEN 'CASE WHEN ' + QUOTENAME(ColumnName) + ' IS NULL THEN 1 ELSE 0 END ASC, ' + QUOTENAME(ColumnName) + ' DESC'
        END,
        ', '
    ) FROM @SortTable ORDER BY SortOrder;

    SET @Sql = N'SELECT ';

    IF @DistinctFlag = 1
        SET @Sql = @Sql + N'DISTINCT ';

    IF @RowLimit IS NOT NULL
        SET @Sql = @Sql + N'TOP ' + CAST(@RowLimit AS NVARCHAR(10)) + N' ';

    SET @Sql = @Sql + @Columns + N' FROM ' + @FullTable;

    IF @WhereClause IS NOT NULL
        SET @Sql = @Sql + N' WHERE ' + @WhereClause;

    SET @Sql = @Sql + N' ORDER BY ' + @SortClause;

    DECLARE @PlanSql NVARCHAR(MAX);
    SET @PlanSql = N'SET STATISTICS TIME ON; SET STATISTICS IO ON; ' + @Sql;
    EXEC sp_executesql @PlanSql;

    DECLARE @CountSql NVARCHAR(MAX);
    SET @CountSql = N'SELECT COUNT(*) AS FilteredCount FROM ' + @FullTable;
    IF @WhereClause IS NOT NULL
        SET @CountSql = @CountSql + N' WHERE ' + @WhereClause;
    EXEC sp_executesql @CountSql;
END;
