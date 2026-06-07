-- ============================================================================
-- Script   : 001_create_source_migration_user.sql
-- Purpose  : Create a least-privilege SQL Server login/user for migration source
--            read access (discovery, row counts, chunked SELECT extraction)
-- Target   : Microsoft SQL Server 2016+ (on-premises or Azure SQL Database)
-- Run as   : sysadmin or securityadmin + db_owner on the target database
-- Depends  : none
-- Variables: Replace placeholders before execution (see :setvar block below)
--
-- Required platform capabilities on source:
--   • SELECT on user tables in the migration schema(s)
--   • sys catalog visibility (columns, keys, indexes, row estimates)
--   • VIEW DEFINITION for DDL/type mapping during target provisioning
--   • VIEW DATABASE STATE for partition row-count estimates (sys.partitions)
--
-- NOT granted (by design):
--   • sysadmin / db_owner / DDL / DML write on source
--   • CDC / replication agent roles (use separate scripts for replication)
--
-- Example  :
--   sqlcmd -S localhost,1433 -U sa -P "<admin-password>" \
--          -v SourceLogin=migration_reader SourcePassword="<secret>" \
--          -v TargetDatabase=source_db \
--          -i infrastructure/sql_scripts/sqlserver/001_create_source_migration_user.sql
--
-- Author   : Migration Platform Team
-- Copyright (c) 2026 Ravi Sharma
-- SPDX-License-Identifier: MIT
-- ============================================================================

:setvar SourceLogin migration_reader
:setvar SourcePassword "ChangeMe_Strong_Password!"
:setvar TargetDatabase source_db
:setvar SourceSchema dbo

-- ── 1. Server login (skip on Azure SQL Database — use contained user in §2) ──

IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name = N'$(SourceLogin)')
BEGIN
    CREATE LOGIN [$(SourceLogin)] WITH PASSWORD = N'$(SourcePassword)',
        CHECK_POLICY = ON,
        CHECK_EXPIRATION = OFF;
END
GO

-- ── 2. Database user + read-only role ───────────────────────────────────────

USE [$(TargetDatabase)];
GO

IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name = N'$(SourceLogin)')
BEGIN
    CREATE USER [$(SourceLogin)] FOR LOGIN [$(SourceLogin)];
END
GO

IF IS_ROLEMEMBER(N'db_datareader', N'$(SourceLogin)') <> 1
BEGIN
    ALTER ROLE db_datareader ADD MEMBER [$(SourceLogin)];
END
GO

-- Metadata discovery (sys.columns, sys.tables, sys.indexes, etc.)
GRANT VIEW DEFINITION TO [$(SourceLogin)];
GO

-- Row-count estimates via sys.partitions during preflight / planning
GRANT VIEW DATABASE STATE TO [$(SourceLogin)];
GO

-- ── 3. Optional: restrict to a single schema (uncomment for tighter scope) ──

-- DENY SELECT ON SCHEMA::dbo TO [$(SourceLogin)];
-- GRANT SELECT ON SCHEMA::[$(SourceSchema)] TO [$(SourceLogin)];

-- ── 4. Verification ───────────────────────────────────────────────────────

SELECT
    dp.name              AS database_user,
    r.name               AS role_name
FROM sys.database_role_members drm
JOIN sys.database_principals dp ON dp.principal_id = drm.member_principal_id
JOIN sys.database_principals r  ON r.principal_id  = drm.role_principal_id
WHERE dp.name = N'$(SourceLogin)';

PRINT 'Source migration user [$(SourceLogin)] is ready on database [$(TargetDatabase)].';
GO
