-- ============================================================
-- Dynamic MERGE / Upsert with Conflict Resolution
-- ============================================================
CREATE PROCEDURE dbo.usp_DynamicMergeData
    @TargetSchema NVARCHAR(128) = 'dbo',
    @TargetTable NVARCHAR(128),
    @SourceSchema NVARCHAR(128) = 'dbo',
    @SourceTable NVARCHAR(128),
    @KeyColumns NVARCHAR(MAX),
    @UpdateColumns NVARCHAR(MAX) = NULL
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @Sql NVARCHAR(MAX);
    DECLARE @FullTarget NVARCHAR(256);
    DECLARE @FullSource NVARCHAR(256);
    DECLARE @JoinCondition NVARCHAR(MAX);
    DECLARE @SetClause NVARCHAR(MAX);
    DECLARE @InsertCols NVARCHAR(MAX);
    DECLARE @SelectCols NVARCHAR(MAX);

    SET @FullTarget = QUOTENAME(@TargetSchema) + N'.' + QUOTENAME(@TargetTable);
    SET @FullSource = QUOTENAME(@SourceSchema) + N'.' + QUOTENAME(@SourceTable);

    DECLARE @KeyTable TABLE (KeyCol NVARCHAR(128));
    INSERT INTO @KeyTable
    SELECT TRIM(value) FROM STRING_SPLIT(@KeyColumns, ',');

    SELECT @JoinCondition = STRING_AGG('T.' + QUOTENAME(KeyCol) + ' = S.' + QUOTENAME(KeyCol), ' AND '),
           @InsertCols = STRING_AGG(QUOTENAME(KeyCol), ', ')
    FROM @KeyTable;

    IF @UpdateColumns IS NULL
    BEGIN
        DECLARE @AllColsSql NVARCHAR(MAX);
        DECLARE @AllCols TABLE (ColName NVARCHAR(128));
        SET @AllColsSql = N'
            SELECT c.name
            FROM sys.columns c
            WHERE c.object_id = OBJECT_ID(@FullTarget)
            ORDER BY c.column_id;';

        DECLARE @AllColsParams NVARCHAR(MAX) = N'@FullTarget NVARCHAR(256)';
        INSERT INTO @AllCols
        EXEC sp_executesql @AllColsSql, @AllColsParams, @FullTarget = @FullTarget;

        SELECT @UpdateColumns = STRING_AGG(ColName, ',') FROM @AllCols;
    END;

    DECLARE @UpdateTable TABLE (Col NVARCHAR(128));
    INSERT INTO @UpdateTable
    SELECT TRIM(value) FROM STRING_SPLIT(@UpdateColumns, ',');

    SELECT @SetClause = STRING_AGG('T.' + QUOTENAME(Col) + ' = S.' + QUOTENAME(Col), ', ')
    FROM @UpdateTable U
    WHERE NOT EXISTS (SELECT 1 FROM @KeyTable K WHERE K.KeyCol = U.Col);

    SELECT @InsertCols = STRING_AGG(QUOTENAME(TRIM(value)), ', '),
           @SelectCols = STRING_AGG('S.' + QUOTENAME(TRIM(value)), ', ')
    FROM STRING_SPLIT(@UpdateColumns, ',');

    SET @Sql = N'
        MERGE ' + @FullTarget + N' AS T
        USING ' + @FullSource + N' AS S
        ON (' + @JoinCondition + N')
        WHEN MATCHED THEN
            UPDATE SET ' + @SetClause + N'
        WHEN NOT MATCHED BY TARGET THEN
            INSERT (' + @InsertCols + N')
            VALUES (' + @SelectCols + N')
        WHEN NOT MATCHED BY SOURCE THEN
            DELETE
        OUTPUT $action, inserted.*, deleted.*;';

    EXEC sp_executesql @Sql;
END;
