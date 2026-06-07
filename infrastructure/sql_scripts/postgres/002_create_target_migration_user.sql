-- ============================================================================
-- Script   : 002_create_target_migration_user.sql
-- Purpose  : Create a scoped PostgreSQL role for migration target operations
--            (DDL provisioning, bulk load, truncate/reload, post-migration validation)
-- Target   : PostgreSQL 14+ (target database — NOT the platform metadata store)
-- Run as   : superuser or a role with CREATEROLE + CREATE on the database
-- Depends  : none
-- Variables: Edit the \set lines below, then run with psql connected to target_db
--
-- Required platform capabilities on target:
--   • CONNECT to the target database
--   • CREATE on the database (to auto-provision schemas like Sales, Person, etc.)
--   • CREATE + USAGE on migration schemas (default: public; plus any source schemas)
--   • CREATE TABLE, TRUNCATE, INSERT, UPDATE, DELETE, SELECT on migrated objects
--
-- NOT granted (by design):
--   • SUPERUSER / CREATEDB / CREATEROLE
--   • Access to platform metadata database (migration_checklist)
--
-- Example  :
--   psql -h localhost -p 5432 -U postgres -d target_db \
--        -f infrastructure/sql_scripts/postgres/002_create_target_migration_user.sql
--
-- Author   : Migration Platform Team
-- Copyright (c) 2026 Ravi Sharma
-- SPDX-License-Identifier: MIT
-- ============================================================================

\set target_user migration_writer
\set target_password 'ChangeMe_Strong_Password!'
\set target_schema public

-- ── 1. Role + login ─────────────────────────────────────────────────────────

SELECT format(
    'CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT',
    :'target_user',
    :'target_password'
) AS stmt
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'target_user')
\gexec

SELECT format('ALTER ROLE %I PASSWORD %L', :'target_user', :'target_password') AS stmt
WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'target_user')
\gexec

-- ── 2. Database connect ─────────────────────────────────────────────────────

SELECT format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), :'target_user') AS stmt
\gexec

SELECT format('GRANT CREATE ON DATABASE %I TO %I', current_database(), :'target_user') AS stmt
\gexec

-- ── 3. Schema (create if missing, then grant DDL/DML) ───────────────────────

SELECT format(
    'CREATE SCHEMA IF NOT EXISTS %I AUTHORIZATION %I',
    :'target_schema',
    :'target_user'
) AS stmt
\gexec

SELECT format('GRANT USAGE, CREATE ON SCHEMA %I TO %I', :'target_schema', :'target_user') AS stmt
\gexec

SELECT format(
    'GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA %I TO %I',
    :'target_schema',
    :'target_user'
) AS stmt
\gexec

SELECT format(
    'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA %I TO %I',
    :'target_schema',
    :'target_user'
) AS stmt
\gexec

SELECT format(
    'ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON TABLES TO %I',
    :'target_schema',
    :'target_user'
) AS stmt
\gexec

SELECT format(
    'ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT USAGE, SELECT ON SEQUENCES TO %I',
    :'target_schema',
    :'target_user'
) AS stmt
\gexec

-- ── 4. Verification ─────────────────────────────────────────────────────────

SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolcanlogin
FROM pg_roles
WHERE rolname = :'target_user';

SELECT
    nspname AS schema_name,
    has_schema_privilege(:'target_user', nspname, 'USAGE')  AS has_usage,
    has_schema_privilege(:'target_user', nspname, 'CREATE') AS has_create
FROM pg_namespace
WHERE nspname = :'target_schema';
