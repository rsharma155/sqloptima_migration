-- ============================================================
-- Dynamic Search with Multiple Filter Combinations
-- ============================================================
CREATE PROCEDURE dbo.usp_DynamicSearch
    @TableName NVARCHAR(128),
    @SearchTerm NVARCHAR(100) = NULL,
    @DateFrom DATE = NULL,
    @DateTo DATE = NULL,
    @CategoryId INT = NULL,
    @Status NVARCHAR(20) = NULL,
    @SortColumn NVARCHAR(50) = 'Id',
    @SortDirection NVARCHAR(4) = 'ASC',
    @PageNumber INT = 1,
    @PageSize INT = 50
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @Sql NVARCHAR(MAX);
    DECLARE @Params NVARCHAR(MAX);
    DECLARE @Offset INT = (@PageNumber - 1) * @PageSize;

    SET @Sql = N'SELECT * FROM ' + QUOTENAME(@TableName) + N' WHERE 1=1';

    IF @SearchTerm IS NOT NULL
        SET @Sql = @Sql + N' AND (Name LIKE @SearchTerm OR Description LIKE @SearchTerm OR Code LIKE @SearchTerm)';

    IF @DateFrom IS NOT NULL
        SET @Sql = @Sql + N' AND CreatedDate >= @DateFrom';

    IF @DateTo IS NOT NULL
        SET @Sql = @Sql + N' AND CreatedDate <= @DateTo';

    IF @CategoryId IS NOT NULL
        SET @Sql = @Sql + N' AND CategoryId = @CategoryId';

    IF @Status IS NOT NULL
        SET @Sql = @Sql + N' AND Status = @Status';

    SET @Sql = @Sql + N' ORDER BY ' + QUOTENAME(@SortColumn) + N' ' + @SortDirection;
    SET @Sql = @Sql + N' OFFSET @Offset ROWS FETCH NEXT @PageSize ROWS ONLY';

    SET @Params = N'@SearchTerm NVARCHAR(100), @DateFrom DATE, @DateTo DATE,
                    @CategoryId INT, @Status NVARCHAR(20), @Offset INT, @PageSize INT';

    EXEC sp_executesql @Sql, @Params,
        @SearchTerm = @SearchTerm,
        @DateFrom = @DateFrom,
        @DateTo = @DateTo,
        @CategoryId = @CategoryId,
        @Status = @Status,
        @Offset = @Offset,
        @PageSize = @PageSize;

    DECLARE @CountSql NVARCHAR(MAX);
    SET @CountSql = N'SELECT COUNT(*) AS TotalCount FROM ' + QUOTENAME(@TableName) + N' WHERE 1=1';

    IF @SearchTerm IS NOT NULL
        SET @CountSql = @CountSql + N' AND (Name LIKE @SearchTerm OR Description LIKE @SearchTerm OR Code LIKE @SearchTerm)';
    IF @DateFrom IS NOT NULL
        SET @CountSql = @CountSql + N' AND CreatedDate >= @DateFrom';
    IF @DateTo IS NOT NULL
        SET @CountSql = @CountSql + N' AND CreatedDate <= @DateTo';
    IF @CategoryId IS NOT NULL
        SET @CountSql = @CountSql + N' AND CategoryId = @CategoryId';
    IF @Status IS NOT NULL
        SET @CountSql = @CountSql + N' AND Status = @Status';

    EXEC sp_executesql @CountSql, @Params,
        @SearchTerm = @SearchTerm,
        @DateFrom = @DateFrom,
        @DateTo = @DateTo,
        @CategoryId = @CategoryId,
        @Status = @Status,
        @Offset = @Offset,
        @PageSize = @PageSize;
END;
