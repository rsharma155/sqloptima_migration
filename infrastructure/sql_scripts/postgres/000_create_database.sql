-- ============================================================================
-- Script   : 000_create_database.sql
-- Purpose  : Create the hosted PostgreSQL metadata database
-- Target   : PostgreSQL 14+ (postgres_checklist Docker service)
-- Database : migration_checklist (created); connect to postgres for this script
-- Revision : n/a (infrastructure bootstrap)
-- Depends  : none
-- Run as   : superuser (e.g. postgres)
-- Example  : psql -h localhost -p 5555 -U postgres -f 000_create_database.sql
-- Author   : Migration Platform Team
-- Copyright (c) 2026 Ravi Sharma
-- SPDX-License-Identifier: MIT
-- ============================================================================

SELECT 'CREATE DATABASE migration_checklist'
WHERE NOT EXISTS (
    SELECT 1 FROM pg_database WHERE datname = 'migration_checklist'
)\gexec
