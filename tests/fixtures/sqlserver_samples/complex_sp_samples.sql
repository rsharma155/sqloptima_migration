-- ============================================================================
-- SQL Server Feature Test Fixture: Complex Stored Procedure Samples
-- Purpose: Comprehensive T-SQL fixture for migration platform testing
-- Contains: Every major SQL Server feature across ALL categories
-- ============================================================================

-- ============================================================================
-- SCHEMA SETUP
-- ============================================================================
--
-- Author: Ravi Sharma
-- Copyright (c) 2026 Ravi Sharma
-- SPDX-License-Identifier: MIT

CREATE SCHEMA migration_tests;
GO

-- ============================================================================
-- PART 1: ALL SQL SERVER DATA TYPES
-- ============================================================================
CREATE TABLE migration_tests.all_data_types (
    -- Exact Numerics
    id_col            INT             NOT NULL IDENTITY(1,1),
    bigint_col        BIGINT          NULL,
    smallint_col      SMALLINT        NULL,
    tinyint_col       TINYINT         NULL,
    bit_col           BIT             NULL,
    decimal_col       DECIMAL(18,2)   NULL,
    numeric_col       NUMERIC(10,4)   NULL,
    money_col         MONEY           NULL,
    smallmoney_col    SMALLMONEY      NULL,

    -- Approximate Numerics
    float_col         FLOAT(53)       NULL,
    real_col          REAL            NULL,

    -- Date and Time
    datetime_col      DATETIME        NULL,
    datetime2_col     DATETIME2(7)    NULL,
    smalldatetime_col SMALLDATETIME   NULL,
    date_col          DATE            NULL,
    time_col          TIME(7)         NULL,
    datetimeoffset_col DATETIMEOFFSET(7) NULL,

    -- Character Strings
    char_col          CHAR(10)        NULL,
    varchar_col       VARCHAR(255)    NULL,
    nchar_col         NCHAR(10)       NULL,
    nvarchar_col      NVARCHAR(MAX)   NULL,
    text_col          TEXT            NULL,
    ntext_col         NTEXT           NULL,

    -- Binary
    binary_col        BINARY(50)      NULL,
    varbinary_col     VARBINARY(MAX)  NULL,
    image_col         IMAGE           NULL,
    rowversion_col    ROWVERSION      NULL,
    timestamp_col     TIMESTAMP       NULL,

    -- Special Types
    uniqueidentifier_col UNIQUEIDENTIFIER NULL DEFAULT NEWID(),
    xml_col           XML             NULL,
    json_col          NVARCHAR(MAX)   NULL,  -- JSON stored as NVARCHAR
    sql_variant_col   SQL_VARIANT     NULL,
    hierarchyid_col   HIERARCHYID     NULL,
    geography_col     GEOGRAPHY       NULL,
    geometry_col      GEOMETRY        NULL,
);
GO

-- ============================================================================
-- PART 2: IDENTITY, SEQUENCE, AND COMPUTED COLUMNS
-- ============================================================================
CREATE TABLE migration_tests.identity_example (
    id           INT IDENTITY(100,5) NOT NULL,
    name         NVARCHAR(100) NOT NULL,
    code         AS 'USR-' + RIGHT('00000' + CAST(id AS VARCHAR(10)), 6),  -- computed (non-persisted)
    full_name    AS (LEFT(name, 50)) PERSISTED,  -- computed (persisted)
    created_at   DATETIME2 DEFAULT GETDATE(),
    updated_at   DATETIME2 DEFAULT GETDATE(),
    row_guid     UNIQUEIDENTIFIER DEFAULT NEWID() ROWGUIDCOL,
);
GO

CREATE SEQUENCE migration_tests.order_seq
    START WITH 1000
    INCREMENT BY 1
    MINVALUE 1
    MAXVALUE 999999
    CYCLE
    CACHE 10;
GO

-- ============================================================================
-- PART 3: ALL CONSTRAINT TYPES
-- ============================================================================
CREATE TABLE migration_tests.orders (
    order_id        INT             NOT NULL,
    customer_id     INT             NOT NULL,
    order_date      DATETIME2       NOT NULL DEFAULT GETDATE(),
    total_amount    DECIMAL(18,2)   NOT NULL CHECK (total_amount >= 0),
    status          VARCHAR(20)     NOT NULL DEFAULT 'PENDING',
    shipping_zip    VARCHAR(10)     NULL,
    discount_code   VARCHAR(20)     NULL,
    is_express      BIT             NOT NULL DEFAULT 0,
    CONSTRAINT PK_orders PRIMARY KEY CLUSTERED (order_id),
    CONSTRAINT CK_orders_status CHECK (status IN ('PENDING', 'SHIPPED', 'DELIVERED', 'CANCELLED')),
    CONSTRAINT DF_orders_order_date DEFAULT GETDATE() FOR order_date,
);
GO

CREATE TABLE migration_tests.order_items (
    item_id         INT IDENTITY(1,1) NOT NULL,
    order_id        INT             NOT NULL,
    product_id      INT             NOT NULL,
    quantity        INT             NOT NULL CHECK (quantity > 0),
    unit_price      DECIMAL(10,2)   NOT NULL,
    CONSTRAINT PK_order_items PRIMARY KEY NONCLUSTERED (item_id),
    CONSTRAINT FK_order_items_orders FOREIGN KEY (order_id)
        REFERENCES migration_tests.orders(order_id)
        ON DELETE CASCADE
        ON UPDATE CASCADE,
    CONSTRAINT UQ_order_items UNIQUE (order_id, product_id),
);
GO

CREATE TABLE migration_tests.customers (
    customer_id     INT             NOT NULL IDENTITY(1,1),
    email           VARCHAR(255)    NOT NULL,
    phone           VARCHAR(20)     NULL,
    CONSTRAINT PK_customers PRIMARY KEY (customer_id),
    CONSTRAINT UQ_customers_email UNIQUE (email),
);
GO

CREATE TABLE migration_tests.audit_log (
    audit_id        INT IDENTITY(1,1) NOT NULL,
    table_name      VARCHAR(100)    NOT NULL,
    action          VARCHAR(20)     NOT NULL,
    old_value       NVARCHAR(MAX)   NULL,
    new_value       NVARCHAR(MAX)   NULL,
    changed_by      VARCHAR(100)    NULL DEFAULT CURRENT_USER,
    changed_at      DATETIME2       NOT NULL DEFAULT GETDATE(),
    CONSTRAINT PK_audit_log PRIMARY KEY CLUSTERED (audit_id),
    CONSTRAINT FK_audit_log_orders FOREIGN KEY (changed_by)
        REFERENCES migration_tests.customers(email)
        ON DELETE SET NULL
        ON UPDATE SET NULL,
);
GO

-- ============================================================================
-- PART 4: ALL INDEX TYPES
-- ============================================================================
-- Clustered Index (on PK above)
-- Nonclustered Index
CREATE NONCLUSTERED INDEX IX_orders_customer_id
    ON migration_tests.orders(customer_id)
    INCLUDE (order_date, total_amount, status);
GO

-- Filtered Index
CREATE NONCLUSTERED INDEX IX_orders_express
    ON migration_tests.orders(order_id)
    WHERE is_express = 1;
GO

-- Unique Index
CREATE UNIQUE NONCLUSTERED INDEX IX_customers_phone
    ON migration_tests.customers(phone)
    WHERE phone IS NOT NULL;
GO

-- Index with options
CREATE NONCLUSTERED INDEX IX_orders_date
    ON migration_tests.orders(order_date DESC)
    INCLUDE (order_id, total_amount)
    WITH (
        FILLFACTOR = 80,
        PAD_INDEX = ON,
        SORT_IN_TEMPDB = ON,
        STATISTICS_NORECOMPUTE = OFF,
        DROP_EXISTING = OFF,
        ONLINE = ON,
        ALLOW_ROW_LOCKS = ON,
        ALLOW_PAGE_LOCKS = ON,
        MAXDOP = 4
    );
GO

-- Full-text Index
CREATE FULLTEXT CATALOG ft_catalog AS DEFAULT;
GO
CREATE FULLTEXT INDEX ON migration_tests.customers(email)
    KEY INDEX PK_customers
    ON ft_catalog
    WITH CHANGE_TRACKING AUTO;
GO

-- XML Index (Primary + Secondary)
CREATE PRIMARY XML INDEX PXI_orders_xml_data
    ON migration_tests.all_data_types(xml_col);
GO

-- Spatial Index
CREATE SPATIAL INDEX SI_geography
    ON migration_tests.all_data_types(geography_col)
    WITH (BOUNDING_BOX = (-180, -90, 180, 90));
GO

CREATE SPATIAL INDEX SI_geometry
    ON migration_tests.all_data_types(geometry_col)
    WITH (BOUNDING_BOX = (-180, -90, 180, 90));
GO

-- Columnstore Index
CREATE CLUSTERED COLUMNSTORE INDEX CCI_analytics
    ON migration_tests.orders;
GO

CREATE NONCLUSTERED COLUMNSTORE INDEX NCCI_order_items
    ON migration_tests.order_items(quantity, unit_price);
GO

-- ============================================================================
-- PART 5: COMPUTED COLUMNS / SPARSE / FILESTREAM
-- ============================================================================
CREATE TABLE migration_tests.documents (
    doc_id          INT IDENTITY(1,1) NOT NULL,
    doc_name        VARCHAR(255) NOT NULL,
    -- Sparse columns (for NULL-heavy data)
    extension       VARCHAR(10) SPARSE NULL,
    file_size_bytes BIGINT       SPARSE NULL,
    checksum        VARCHAR(64)  SPARSE NULL,
    -- Computed columns
    file_size_mb    AS (CAST(file_size_bytes AS DECIMAL(18,2)) / 1048576.0) PERSISTED,
    file_extension  AS RIGHT(doc_name, CHARINDEX('.', REVERSE(doc_name)) - 1),
);
GO

-- ============================================================================
-- PART 6: PARTITIONED TABLE
-- ============================================================================
CREATE PARTITION FUNCTION pf_order_date (DATETIME2)
    AS RANGE RIGHT FOR VALUES (
        '2023-01-01', '2023-04-01', '2023-07-01', '2023-10-01',
        '2024-01-01', '2024-04-01', '2024-07-01', '2024-10-01',
        '2025-01-01'
    );
GO

CREATE PARTITION SCHEME ps_order_date
    AS PARTITION pf_order_date
    ALL TO ([PRIMARY]);
GO

CREATE TABLE migration_tests.partitioned_orders (
    order_id        INT             NOT NULL,
    order_date      DATETIME2       NOT NULL,
    customer_id     INT             NOT NULL,
    total_amount    DECIMAL(18,2)   NOT NULL,
    CONSTRAINT PK_partitioned_orders PRIMARY KEY (order_id, order_date)
) ON ps_order_date(order_date);
GO

-- ============================================================================
-- PART 7: TEMPORAL TABLE (System-Versioned)
-- ============================================================================
CREATE TABLE migration_tests.employees (
    employee_id     INT IDENTITY(1,1) NOT NULL,
    name            NVARCHAR(100)   NOT NULL,
    department      VARCHAR(50)     NOT NULL,
    salary          DECIMAL(18,2)   NOT NULL,
    valid_from      DATETIME2       GENERATED ALWAYS AS ROW START NOT NULL,
    valid_to        DATETIME2       GENERATED ALWAYS AS ROW END NOT NULL,
    PERIOD FOR SYSTEM_TIME (valid_from, valid_to),
    CONSTRAINT PK_employees PRIMARY KEY (employee_id),
) WITH (SYSTEM_VERSIONING = ON (HISTORY_TABLE = migration_tests.employees_history));
GO

-- ============================================================================
-- PART 8: CDC AND CHANGE TRACKING
-- ============================================================================
-- CDC enabled at database level
EXEC sys.sp_cdc_enable_db;
GO
EXEC sys.sp_cdc_enable_table
    @source_schema = 'migration_tests',
    @source_name = 'orders',
    @role_name = NULL,
    @filegroup_name = 'PRIMARY',
    @supports_net_changes = 1;
GO

-- Change Tracking
ALTER TABLE migration_tests.customers
    ENABLE CHANGE_TRACKING
    WITH (TRACK_COLUMNS_UPDATED = ON);
GO

-- ============================================================================
-- PART 9: VIEWS (Standard, Indexed, Partitioned)
-- ============================================================================
-- Standard View
CREATE VIEW migration_tests.v_order_summary
AS
SELECT
    o.order_id,
    o.order_date,
    o.total_amount,
    o.status,
    c.email AS customer_email,
    COUNT(oi.item_id) AS item_count
FROM migration_tests.orders o
    INNER JOIN migration_tests.customers c ON o.customer_id = c.customer_id
    LEFT JOIN migration_tests.order_items oi ON o.order_id = oi.order_id
GROUP BY o.order_id, o.order_date, o.total_amount, o.status, c.email;
GO

-- Indexed (Materialized) View
CREATE VIEW migration_tests.v_order_totals WITH SCHEMABINDING
AS
SELECT
    o.customer_id,
    c.email,
    COUNT_BIG(*) AS order_count,
    SUM(o.total_amount) AS total_spent
FROM migration_tests.orders o
    INNER JOIN migration_tests.customers c ON o.customer_id = c.customer_id
GROUP BY o.customer_id, c.email;
GO

CREATE UNIQUE CLUSTERED INDEX IX_v_order_totals_customer
    ON migration_tests.v_order_totals(customer_id);
GO

-- Partitioned View
CREATE VIEW migration_tests.v_all_orders
AS
    SELECT * FROM migration_tests.orders
    UNION ALL
    SELECT * FROM migration_tests.partitioned_orders;
GO

-- ============================================================================
-- PART 10: TRIGGERS (AFTER, INSTEAD OF, DDL, LOGON)
-- ============================================================================
-- AFTER Trigger
CREATE TRIGGER migration_tests.trg_orders_audit
    ON migration_tests.orders
    AFTER INSERT, UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    INSERT INTO migration_tests.audit_log (table_name, action, old_value, new_value)
    SELECT 'orders', 'INSERT', NULL, (SELECT * FROM inserted FOR XML AUTO);
END;
GO

-- INSTEAD OF Trigger
CREATE TRIGGER migration_tests.trg_customers_protect
    ON migration_tests.customers
    INSTEAD OF DELETE
AS
BEGIN
    SET NOCOUNT ON;
    RAISERROR('Deletion of customers is not allowed. Use soft delete.', 16, 1);
    ROLLBACK TRANSACTION;
END;
GO

-- DDL Trigger
CREATE TRIGGER trg_ddl_prevent_drop
    ON DATABASE
    FOR DROP_TABLE, DROP_PROCEDURE, DROP_FUNCTION
AS
BEGIN
    SET NOCOUNT ON;
    RAISERROR('DROP operations are logged and restricted in this environment.', 16, 1);
    ROLLBACK;
END;
GO

-- LOGON Trigger (server level)
CREATE TRIGGER trg_logon_audit
    ON ALL SERVER
    FOR LOGON
AS
BEGIN
    IF ORIGINAL_LOGIN() NOT IN ('sa', 'admin')
    BEGIN
        ROLLBACK;
    END
END;
GO

-- ============================================================================
-- PART 11: FUNCTIONS (Scalar, Inline TVF, Multi-statement TVF)
-- ============================================================================
-- Scalar Function
CREATE FUNCTION migration_tests.fn_calculate_discount (
    @total DECIMAL(18,2),
    @customer_rank INT
)
RETURNS DECIMAL(18,2)
AS
BEGIN
    DECLARE @discount DECIMAL(18,2);
    SET @discount = CASE
        WHEN @customer_rank >= 5 THEN @total * 0.20
        WHEN @customer_rank >= 3 THEN @total * 0.10
        WHEN @customer_rank >= 1 THEN @total * 0.05
        ELSE 0
    END;
    RETURN @discount;
END;
GO

-- Inline Table-Valued Function
CREATE FUNCTION migration_tests.fn_get_orders_by_status (
    @status VARCHAR(20)
)
RETURNS TABLE
AS
RETURN (
    SELECT
        o.order_id,
        o.order_date,
        o.total_amount,
        c.email
    FROM migration_tests.orders o
        INNER JOIN migration_tests.customers c ON o.customer_id = c.customer_id
    WHERE o.status = @status
);
GO

-- Multi-statement Table-Valued Function
CREATE FUNCTION migration_tests.fn_get_order_statistics (
    @start_date DATETIME2,
    @end_date DATETIME2
)
RETURNS @result TABLE (
    status VARCHAR(20),
    order_count INT,
    total_amount DECIMAL(18,2),
    avg_amount DECIMAL(18,2),
    min_amount DECIMAL(18,2),
    max_amount DECIMAL(18,2)
)
AS
BEGIN
    INSERT INTO @result
    SELECT
        status,
        COUNT(*) AS order_count,
        SUM(total_amount) AS total_amount,
        AVG(total_amount) AS avg_amount,
        MIN(total_amount) AS min_amount,
        MAX(total_amount) AS max_amount
    FROM migration_tests.orders
    WHERE order_date BETWEEN @start_date AND @end_date
    GROUP BY status;

    -- If no orders, insert default row
    IF @@ROWCOUNT = 0
    BEGIN
        INSERT INTO @result VALUES ('NO_DATA', 0, 0, 0, 0, 0);
    END

    RETURN;
END;
GO

-- Function calling other functions (scalar in TVF)
CREATE FUNCTION migration_tests.fn_get_discounted_orders (
    @customer_rank INT
)
RETURNS TABLE
AS
RETURN (
    SELECT
        order_id,
        total_amount,
        migration_tests.fn_calculate_discount(total_amount, @customer_rank) AS discount
    FROM migration_tests.orders
);
GO

-- ============================================================================
-- PART 12: COMPLEX STORED PROCEDURE (ALL MAJOR T-SQL FEATURES)
-- ============================================================================
CREATE PROCEDURE migration_tests.usp_process_orders
    @customer_id        INT = NULL,
    @status_filter      VARCHAR(20) = NULL,
    @process_all        BIT = 0,
    @batch_size         INT = 100,
    @output_count       INT = 0 OUTPUT,
    @error_message      NVARCHAR(MAX) = NULL OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    BEGIN TRY
        -- Variable declarations
        DECLARE @current_order_id INT;
        DECLARE @current_total DECIMAL(18,2);
        DECLARE @current_status VARCHAR(20);
        DECLARE @sql NVARCHAR(MAX);
        DECLARE @params NVARCHAR(MAX);
        DECLARE @batch_counter INT = 0;
        DECLARE @processed_count INT = 0;
        DECLARE @savepoint_name VARCHAR(30);

        -- Table variable
        DECLARE @orders_to_process TABLE (
            order_id INT PRIMARY KEY,
            total_amount DECIMAL(18,2),
            current_status VARCHAR(20),
            processed BIT DEFAULT 0
        );

        -- Temporary table
        CREATE TABLE #order_errors (
            error_id INT IDENTITY(1,1),
            order_id INT,
            error_message NVARCHAR(MAX),
            created_at DATETIME2 DEFAULT GETDATE()
        );

        -- CTE to get orders
        WITH filtered_orders AS (
            SELECT
                o.order_id,
                o.total_amount,
                o.status,
                ROW_NUMBER() OVER (ORDER BY o.order_date DESC) AS rn,
                LAG(o.total_amount) OVER (ORDER BY o.order_date) AS prev_total,
                LEAD(o.status) OVER (ORDER BY o.order_date) AS next_status
            FROM migration_tests.orders o
            WHERE (o.customer_id = @customer_id OR @customer_id IS NULL)
              AND (o.status = @status_filter OR @status_filter IS NULL)
        )
        INSERT INTO @orders_to_process (order_id, total_amount, current_status)
        SELECT order_id, total_amount, status
        FROM filtered_orders
        WHERE rn <= @batch_size
        ORDER BY order_id;

        -- CURSOR to loop through orders
        DECLARE order_cursor CURSOR FAST_FORWARD FOR
            SELECT order_id, total_amount, current_status
            FROM @orders_to_process
            WHERE processed = 0;

        OPEN order_cursor;
        FETCH NEXT FROM order_cursor INTO @current_order_id, @current_total, @current_status;

        WHILE @@FETCH_STATUS = 0
        BEGIN
            SET @batch_counter = @batch_counter + 1;

            -- Nested IF/ELSE logic
            IF @current_status = 'PENDING'
            BEGIN
                -- Use SAVE TRANSACTION for partial rollback
                SET @savepoint_name = 'OrderSP_' + CAST(@current_order_id AS VARCHAR);
                SAVE TRANSACTION @savepoint_name;

                -- Dynamic SQL with sp_executesql
                SET @sql = N'
                    UPDATE migration_tests.orders
                    SET status = @new_status,
                        total_amount = @total
                    WHERE order_id = @oid';

                SET @params = N'
                    @new_status NVARCHAR(20),
                    @total DECIMAL(18,2),
                    @oid INT';

                EXEC sp_executesql @sql, @params,
                    @new_status = N'PROCESSING',
                    @total = @current_total,
                    @oid = @current_order_id;

                -- MERGE into audit
                MERGE migration_tests.audit_log AS target
                USING (SELECT @current_order_id AS order_id) AS source
                ON (target.table_name = 'orders' AND target.action = 'PROCESSED' AND target.new_value LIKE '%' + CAST(source.order_id AS VARCHAR) + '%')
                WHEN NOT MATCHED THEN
                    INSERT (table_name, action, new_value)
                    VALUES ('orders', 'PROCESSED', 'Order ' + CAST(@current_order_id AS VARCHAR) + ' processed');

                -- Check @@ROWCOUNT
                IF @@ROWCOUNT > 0
                BEGIN
                    SET @processed_count = @processed_count + 1;
                END

                -- CASE expression
                UPDATE @orders_to_process
                SET processed = 1
                WHERE order_id = @current_order_id;

                -- CONTINUE if batch limit reached
                IF @batch_counter >= @batch_size AND @process_all = 0
                BEGIN
                    BREAK;
                END
                ELSE
                BEGIN
                    CONTINUE;
                END
            END
            ELSE IF @current_status = 'SHIPPED'
            BEGIN
                -- PIVOT example via dynamic SQL
                SET @sql = N'
                    SELECT pivoted.*
                    FROM (
                        SELECT order_id, status, total_amount
                        FROM migration_tests.orders
                        WHERE customer_id = @cid
                    ) src
                    PIVOT (
                        SUM(total_amount)
                        FOR status IN ([PENDING], [PROCESSING], [SHIPPED], [DELIVERED], [CANCELLED])
                    ) pivoted';
                EXEC sp_executesql @sql, N'@cid INT', @cid = @customer_id;

                -- CROSS APPLY
                SELECT o.order_id, o.total_amount, f.discount
                FROM migration_tests.orders o
                    CROSS APPLY migration_tests.fn_calculate_discount(o.total_amount, 1) AS f(discount)
                WHERE o.order_id = @current_order_id;
            END

            FETCH NEXT FROM order_cursor INTO @current_order_id, @current_total, @current_status;
        END

        CLOSE order_cursor;
        DEALLOCATE order_cursor;

        -- OUTPUT parameter
        SET @output_count = @processed_count;

        -- OUTPUT clause example
        DECLARE @deleted_ids TABLE (id INT);
        DELETE FROM @orders_to_process
        OUTPUT DELETED.order_id INTO @deleted_ids
        WHERE processed = 1;

        -- JSON output
        SELECT
            @processed_count AS processed_count,
            (SELECT order_id, total_amount
             FROM migration_tests.orders
             WHERE customer_id = @customer_id
             FOR JSON PATH) AS orders_json;

        -- XML output
        SELECT
            order_id, total_amount, status
        FROM migration_tests.orders
        WHERE customer_id = @customer_id
        FOR XML PATH('order'), ROOT('orders');

        -- Explicit transaction
        IF @processed_count > 0
        BEGIN
            BEGIN TRANSACTION;
                INSERT INTO migration_tests.audit_log (table_name, action, new_value)
                VALUES ('orders', 'BATCH_PROCESS', 'Processed ' + CAST(@processed_count AS VARCHAR) + ' orders');
            COMMIT TRANSACTION;
        END

    END TRY
    BEGIN CATCH
        -- Error handling
        SET @error_message = ERROR_MESSAGE();

        -- Cleanup cursor if open
        IF CURSOR_STATUS('local', 'order_cursor') >= 0
        BEGIN
            CLOSE order_cursor;
            DEALLOCATE order_cursor;
        END

        -- Rollback any open transaction
        IF @@TRANCOUNT > 0
        BEGIN
            ROLLBACK TRANSACTION;
        END

        -- Raise error
        DECLARE @error_msg NVARCHAR(MAX) = 'Error processing orders: ' + ERROR_MESSAGE();
        RAISERROR(@error_msg, 16, 1);
    END CATCH

    -- RETURN value
    RETURN @processed_count;
END;
GO

-- ============================================================================
-- PART 13: NESTED AND RECURSIVE SP CALLS
-- ============================================================================
CREATE PROCEDURE migration_tests.usp_send_notification
    @customer_id INT,
    @message NVARCHAR(MAX),
    @notification_id INT = 0 OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    SET @notification_id = @customer_id * 1000 + CAST(RAND() * 999 AS INT);
    INSERT INTO migration_tests.audit_log (table_name, action, new_value)
    VALUES ('notifications', 'SENT', @message);
END;
GO

CREATE PROCEDURE migration_tests.usp_create_order
    @customer_id INT,
    @total DECIMAL(18,2),
    @order_id INT = 0 OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    INSERT INTO migration_tests.orders (customer_id, total_amount)
    VALUES (@customer_id, @total);
    SET @order_id = SCOPE_IDENTITY();
END;
GO

-- Nested SP: This SP calls usp_create_order and usp_send_notification
CREATE PROCEDURE migration_tests.usp_place_order_full
    @customer_id        INT,
    @total              DECIMAL(18,2),
    @send_notification   BIT = 1,
    @order_id           INT = 0 OUTPUT,
    @notification_id    INT = 0 OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @local_error INT = 0;

    BEGIN TRANSACTION;
        -- Nested SP call #1
        EXEC migration_tests.usp_create_order
            @customer_id = @customer_id,
            @total = @total,
            @order_id = @order_id OUTPUT;

        -- Nested SP call #2 (with notification)
        IF @send_notification = 1
        BEGIN
            EXEC migration_tests.usp_send_notification
                @customer_id = @customer_id,
                @message = N'Order ' + CAST(@order_id AS NVARCHAR) + ' created',
                @notification_id = @notification_id OUTPUT;
        END

        SET @local_error = @@ERROR;
    IF @local_error = 0
        COMMIT TRANSACTION;
    ELSE
        ROLLBACK TRANSACTION;

    RETURN @local_error;
END;
GO

-- Recursive SP: Calculate factorial
CREATE PROCEDURE migration_tests.usp_factorial
    @n INT,
    @result BIGINT = 1 OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    IF @n <= 1
    BEGIN
        SET @result = 1;
        RETURN @result;
    END

    DECLARE @sub_result BIGINT;
    EXEC migration_tests.usp_factorial @n = @n - 1, @result = @sub_result OUTPUT;
    SET @result = @n * @sub_result;
    RETURN @result;
END;
GO

-- ============================================================================
-- PART 14: CTE, WINDOW FUNCTIONS, HIERARCHICAL QUERIES
-- ============================================================================
-- Recursive CTE (Hierarchical)
CREATE PROCEDURE migration_tests.usp_get_org_chart
    @manager_id INT = NULL
AS
BEGIN
    SET NOCOUNT ON;
    WITH org_tree AS (
        -- Anchor
        SELECT
            employee_id,
            name,
            department,
            0 AS level
        FROM migration_tests.employees
        WHERE employee_id = @manager_id OR @manager_id IS NULL

        UNION ALL

        -- Recursive
        SELECT
            e.employee_id,
            e.name,
            e.department,
            t.level + 1
        FROM migration_tests.employees e
            INNER JOIN org_tree t ON e.employee_id = t.employee_id
    )
    SELECT * FROM org_tree;
END;
GO

-- Window functions in SP
CREATE PROCEDURE migration_tests.usp_get_ranked_orders
    @year INT = NULL
AS
BEGIN
    SET NOCOUNT ON;
    SELECT
        order_id,
        customer_id,
        total_amount,
        order_date,
        ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY total_amount DESC) AS rn,
        RANK() OVER (ORDER BY total_amount DESC) AS sales_rank,
        DENSE_RANK() OVER (ORDER BY total_amount DESC) AS dense_sales_rank,
        NTILE(4) OVER (ORDER BY total_amount DESC) AS quartile,
        LAG(total_amount, 1, 0) OVER (ORDER BY order_date) AS prev_amount,
        LEAD(total_amount, 1, 0) OVER (ORDER BY order_date) AS next_amount,
        SUM(total_amount) OVER (PARTITION BY customer_id) AS customer_total,
        AVG(total_amount) OVER () AS avg_order_value,
        COUNT(*) OVER () AS total_orders
    FROM migration_tests.orders
    WHERE YEAR(order_date) = @year OR @year IS NULL
    ORDER BY order_date;
END;
GO

-- ============================================================================
-- PART 15: SYNONYM
-- ============================================================================
CREATE SYNONYM migration_tests.orders_sync
    FOR migration_tests.orders;
GO

CREATE SYNONYM migration_tests.process_orders
    FOR migration_tests.usp_process_orders;
GO

-- ============================================================================
-- PART 16: TVP (Table-Valued Parameter) SETUP
-- ============================================================================
CREATE TYPE migration_tests.dbo.OrderItemType AS TABLE (
    product_id   INT NOT NULL,
    quantity     INT NOT NULL,
    unit_price   DECIMAL(10,2) NOT NULL,
    PRIMARY KEY (product_id)
);
GO

CREATE PROCEDURE migration_tests.usp_bulk_insert_items
    @order_id INT,
    @items migration_tests.dbo.OrderItemType READONLY
AS
BEGIN
    SET NOCOUNT ON;
    INSERT INTO migration_tests.order_items (order_id, product_id, quantity, unit_price)
    SELECT @order_id, product_id, quantity, unit_price
    FROM @items;
END;
GO

-- ============================================================================
-- PART 17: STRING MANIPULATION AND DATA FUNCTIONS
-- ============================================================================
CREATE PROCEDURE migration_tests.usp_process_strings
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @sample VARCHAR(MAX) = '  Hello, World!  ';
    DECLARE @result VARCHAR(MAX);

    -- String functions
    SET @result = CHARINDEX('World', @sample);
    SET @result = PATINDEX('%[Ww]orld%', @sample);
    SET @result = SUBSTRING(@sample, 3, 5);
    SET @result = REPLACE(@sample, 'Hello', 'Hi');
    SET @result = STUFF(@sample, 1, 2, 'XX');
    SET @result = UPPER(@sample);
    SET @result = LOWER(@sample);
    SET @result = LTRIM(RTRIM(@sample));
    SET @result = LEFT(@sample, 5);
    SET @result = RIGHT(@sample, 5);
    SET @result = REVERSE(@sample);
    SET @result = REPLICATE('AB', 3);
    SET @result = SPACE(5);
    SET @result = LEN(@sample);

    -- Date functions
    DECLARE @now DATETIME2 = GETDATE();
    DECLARE @utc DATETIME2 = GETUTCDATE();
    DECLARE @date DATE = GETDATE();
    SET @result = DATEADD(day, 7, @now);
    SET @result = DATEDIFF(day, @now, DATEADD(year, 1, @now));
    SET @result = DATEPART(year, @now);
    SET @result = DATENAME(month, @now);
    SET @result = EOMONTH(@now);
    SET @result = YEAR(@now);
    SET @result = MONTH(@now);
    SET @result = DAY(@now);

    -- Aggregate functions
    SELECT
        SUM(total_amount) AS sum_amount,
        COUNT(*) AS order_count,
        MIN(total_amount) AS min_amount,
        MAX(total_amount) AS max_amount,
        AVG(total_amount) AS avg_amount,
        STRING_AGG(CAST(order_id AS VARCHAR), ',') AS order_ids
    FROM migration_tests.orders;

    -- System functions
    SELECT
        @@ROWCOUNT AS rows_affected,
        @@IDENTITY AS last_id,
        SCOPE_IDENTITY() AS scope_last_id,
        @@ERROR AS last_error,
        @@TRANCOUNT AS active_transactions;

    -- JSON functions
    DECLARE @json NVARCHAR(MAX) = N'{"name": "John", "age": 30}';
    SELECT
        JSON_VALUE(@json, '$.name') AS name,
        JSON_QUERY(@json, '$.name') AS name_obj,
        * FROM OPENJSON(@json);

    SELECT * FROM migration_tests.orders
    FOR JSON PATH, ROOT('orders');

END;
GO

-- ============================================================================
-- PART 18: PIVOT/UNPIVOT, CROSS/OUTER APPLY
-- ============================================================================
CREATE PROCEDURE migration_tests.usp_pivot_demo
AS
BEGIN
    SET NOCOUNT ON;
    -- PIVOT
    SELECT *
    FROM (
        SELECT YEAR(order_date) AS order_year,
               DATENAME(month, order_date) AS order_month,
               total_amount
        FROM migration_tests.orders
    ) src
    PIVOT (
        SUM(total_amount)
        FOR order_month IN ([January], [February], [March], [April], [May], [June],
                            [July], [August], [September], [October], [November], [December])
    ) pvt;

    -- UNPIVOT
    SELECT *
    FROM (
        SELECT customer_id, SUM(total_amount) AS total
        FROM migration_tests.orders
        GROUP BY customer_id
    ) src
    UNPIVOT (
        amount FOR amount_type IN (total)
    ) unpvt;
END;
GO

-- ============================================================================
-- PART 19: OUTPUT CLAUSE
-- ============================================================================
CREATE PROCEDURE migration_tests.usp_insert_with_output
    @customer_id INT,
    @total DECIMAL(18,2),
    @new_order_id INT OUTPUT
AS
BEGIN
    SET NOCOUNT ON;
    INSERT INTO migration_tests.orders (customer_id, total_amount)
    OUTPUT INSERTED.order_id
    VALUES (@customer_id, @total);

    SET @new_order_id = SCOPE_IDENTITY();
END;
GO

-- ============================================================================
-- PART 20: TRANSACTION MANAGEMENT
-- ============================================================================
CREATE PROCEDURE migration_tests.usp_transaction_demo
    @should_commit BIT = 1
AS
BEGIN
    SET NOCOUNT ON;

    BEGIN TRANSACTION;

        UPDATE migration_tests.orders SET status = 'PENDING';
        SAVE TRANSACTION after_update;

        INSERT INTO migration_tests.audit_log (table_name, action)
        VALUES ('orders', 'TRANSACTION_DEMO');

        IF @should_commit = 1
        BEGIN
            COMMIT TRANSACTION;
        END
        ELSE
        BEGIN
            ROLLBACK TRANSACTION;
        END
END;
GO

PRINT 'All SQL Server feature samples loaded successfully.';
GO
