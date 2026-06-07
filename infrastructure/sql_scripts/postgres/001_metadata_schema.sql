-- ============================================================================
-- Script   : 001_metadata_schema.sql
-- Purpose  : Full platform metadata schema for hosted PostgreSQL (head)
-- Target   : PostgreSQL 14+ / database migration_checklist
-- Revision : head
-- ORM      : infrastructure/metadata_db/models.py
-- Convention: Primary keys are named after their table (e.g. migration_job_id)
-- Depends  : 000_create_database.sql (optional)
-- Usage    :
--   psql -h localhost -p 5555 -U postgres -d migration_checklist \
--        -f infrastructure/sql_scripts/postgres/001_metadata_schema.sql
-- Author   : Migration Platform Team
-- Copyright (c) 2026 Ravi Sharma
-- SPDX-License-Identifier: MIT
-- ============================================================================

BEGIN;

-- ── Connections (no FK deps) ───────────────────────────────────────────────

CREATE TABLE project_connections (
    project_connection_id   VARCHAR(36)  NOT NULL,
    name                    VARCHAR(255) NOT NULL,
    db_type                 VARCHAR(20)  NOT NULL,
    host                    VARCHAR(255) NOT NULL,
    port                    INTEGER      NOT NULL,
    database_name           VARCHAR(255) NOT NULL,
    username                VARCHAR(255) NOT NULL,
    encrypted_password      TEXT         NOT NULL,
    ssl_enabled             BOOLEAN      NOT NULL DEFAULT FALSE,
    vault_ref               VARCHAR(512),
    project_id              VARCHAR(36),
    created_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_tested_at          TIMESTAMPTZ,
    last_test_ok            BOOLEAN,
    CONSTRAINT pk_project_connections PRIMARY KEY (project_connection_id)
);

-- ── Auth ─────────────────────────────────────────────────────────────────────

CREATE TABLE auth_users (
    auth_user_id    VARCHAR(36)  NOT NULL,
    email           VARCHAR(255) NOT NULL,
    username        VARCHAR(100) NOT NULL,
    password_hash   VARCHAR(512) NOT NULL,
    role            VARCHAR(20)  NOT NULL DEFAULT 'viewer',
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_login_at   TIMESTAMPTZ,
    CONSTRAINT pk_auth_users PRIMARY KEY (auth_user_id),
    CONSTRAINT uq_auth_users_email UNIQUE (email),
    CONSTRAINT uq_auth_users_username UNIQUE (username)
);

CREATE INDEX ix_auth_users_email ON auth_users (email);
CREATE INDEX ix_auth_users_username ON auth_users (username);

CREATE TABLE auth_sessions (
    auth_session_id     VARCHAR(36)  NOT NULL,
    auth_user_id        VARCHAR(36)  NOT NULL,
    refresh_token_hash  VARCHAR(512) NOT NULL,
    expires_at          TIMESTAMPTZ  NOT NULL,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT pk_auth_sessions PRIMARY KEY (auth_session_id),
    CONSTRAINT uq_sessions_token_hash UNIQUE (refresh_token_hash),
    CONSTRAINT fk_auth_sessions_user
        FOREIGN KEY (auth_user_id) REFERENCES auth_users (auth_user_id) ON DELETE CASCADE
);

CREATE INDEX ix_auth_sessions_auth_user_id ON auth_sessions (auth_user_id);

CREATE TABLE auth_token_denylist (
    jti         VARCHAR(36) NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL,
    revoked_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT pk_auth_token_denylist PRIMARY KEY (jti)
);

CREATE INDEX ix_auth_token_denylist_expires_at ON auth_token_denylist (expires_at);

-- ── Projects ─────────────────────────────────────────────────────────────────

CREATE TABLE project_projects (
    project_id                      VARCHAR(36)  NOT NULL,
    name                            VARCHAR(255) NOT NULL,
    description                     TEXT,
    source_project_connection_id    VARCHAR(36),
    target_project_connection_id    VARCHAR(36),
    created_by_auth_user_id         VARCHAR(36),
    created_at                      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at                      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT pk_project_projects PRIMARY KEY (project_id),
    CONSTRAINT uq_project_projects_name UNIQUE (name),
    CONSTRAINT fk_project_projects_source
        FOREIGN KEY (source_project_connection_id)
        REFERENCES project_connections (project_connection_id) ON DELETE SET NULL,
    CONSTRAINT fk_project_projects_target
        FOREIGN KEY (target_project_connection_id)
        REFERENCES project_connections (project_connection_id) ON DELETE SET NULL,
    CONSTRAINT fk_project_projects_created_by
        FOREIGN KEY (created_by_auth_user_id)
        REFERENCES auth_users (auth_user_id) ON DELETE SET NULL
);

CREATE INDEX ix_project_projects_name ON project_projects (name);
CREATE INDEX ix_project_projects_src_conn ON project_projects (source_project_connection_id);
CREATE INDEX ix_project_projects_tgt_conn ON project_projects (target_project_connection_id);

ALTER TABLE project_connections
    ADD CONSTRAINT fk_connections_project
        FOREIGN KEY (project_id) REFERENCES project_projects (project_id) ON DELETE SET NULL;

CREATE INDEX ix_project_connections_project_id ON project_connections (project_id);

-- ── Migration jobs ───────────────────────────────────────────────────────────

CREATE TABLE migration_jobs (
    migration_job_id                VARCHAR(36)  NOT NULL,
    source_project_connection_id    VARCHAR(36),
    target_project_connection_id    VARCHAR(36),
    status                          VARCHAR(20)  NOT NULL,
    tables_total                    INTEGER      NOT NULL DEFAULT 0,
    tables_done                     INTEGER      NOT NULL DEFAULT 0,
    rows_total                      BIGINT       NOT NULL DEFAULT 0,
    rows_migrated                   BIGINT       NOT NULL DEFAULT 0,
    started_at                      TIMESTAMPTZ,
    completed_at                    TIMESTAMPTZ,
    error                           TEXT,
    config                          JSONB,
    executor                        VARCHAR(20)  NOT NULL DEFAULT 'go',
    workflow_handle_id              VARCHAR(255),
    project_id                      VARCHAR(36),
    created_at                      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at                      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT pk_migration_jobs PRIMARY KEY (migration_job_id),
    CONSTRAINT fk_migration_jobs_source
        FOREIGN KEY (source_project_connection_id)
        REFERENCES project_connections (project_connection_id) ON DELETE SET NULL,
    CONSTRAINT fk_migration_jobs_target
        FOREIGN KEY (target_project_connection_id)
        REFERENCES project_connections (project_connection_id) ON DELETE SET NULL
);

CREATE INDEX ix_migration_jobs_status ON migration_jobs (status);
CREATE INDEX ix_migration_jobs_src ON migration_jobs (source_project_connection_id);
CREATE INDEX ix_migration_jobs_tgt ON migration_jobs (target_project_connection_id);
CREATE INDEX ix_migration_jobs_workflow_handle ON migration_jobs (workflow_handle_id);
CREATE INDEX ix_migration_jobs_project_id ON migration_jobs (project_id);

CREATE TABLE migration_table_plans (
    migration_table_plan_id SERIAL       NOT NULL,
    migration_job_id        VARCHAR(36)  NOT NULL,
    table_name              VARCHAR(255) NOT NULL,
    schema_name             VARCHAR(255) NOT NULL,
    target_schema           VARCHAR(255) NOT NULL DEFAULT 'public',
    strategy                VARCHAR(50)  NOT NULL,
    chunk_size              INTEGER      NOT NULL,
    parallel_workers        INTEGER      NOT NULL,
    status                  VARCHAR(50)  NOT NULL,
    rows_migrated           BIGINT       NOT NULL DEFAULT 0,
    row_count_estimate      BIGINT       NOT NULL DEFAULT 0,
    columns                 JSONB,
    plan_config             JSONB,
    CONSTRAINT pk_migration_table_plans PRIMARY KEY (migration_table_plan_id),
    CONSTRAINT fk_table_plans_job
        FOREIGN KEY (migration_job_id) REFERENCES migration_jobs (migration_job_id) ON DELETE CASCADE
);

CREATE INDEX ix_table_plans_job_table ON migration_table_plans (migration_job_id, table_name);

CREATE TABLE migration_job_logs (
    migration_job_log_id  SERIAL       NOT NULL,
    migration_job_id      VARCHAR(36)  NOT NULL,
    logged_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    level                 VARCHAR(20)  NOT NULL DEFAULT 'info',
    message               TEXT         NOT NULL,
    CONSTRAINT pk_migration_job_logs PRIMARY KEY (migration_job_log_id),
    CONSTRAINT fk_migration_job_logs_job
        FOREIGN KEY (migration_job_id) REFERENCES migration_jobs (migration_job_id) ON DELETE CASCADE
);

CREATE INDEX ix_migration_job_logs_job_time ON migration_job_logs (migration_job_id, logged_at);

CREATE TABLE migration_worker_heartbeats (
    worker_id       VARCHAR(128) NOT NULL,
    last_seen_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    engine_version  VARCHAR(32)  NOT NULL DEFAULT '0.1.0',
    status          VARCHAR(32)  NOT NULL DEFAULT 'idle',
    CONSTRAINT pk_migration_worker_heartbeats PRIMARY KEY (worker_id)
);

CREATE TABLE migration_commands (
    migration_job_id    VARCHAR(36)  NOT NULL,
    command             VARCHAR(20)  NOT NULL,
    issued_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    acked_at            TIMESTAMPTZ,
    CONSTRAINT pk_migration_commands PRIMARY KEY (migration_job_id),
    CONSTRAINT fk_migration_commands_job
        FOREIGN KEY (migration_job_id) REFERENCES migration_jobs (migration_job_id) ON DELETE CASCADE
);

CREATE TABLE migration_quarantine (
    migration_quarantine_id VARCHAR(36)  NOT NULL,
    migration_job_id        VARCHAR(36)  NOT NULL,
    table_schema            VARCHAR(255),
    table_name              VARCHAR(255),
    row_pk_value            TEXT,
    error_column            VARCHAR(255),
    error_type              VARCHAR(100),
    source_value            TEXT,
    error_message           TEXT,
    created_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT pk_migration_quarantine PRIMARY KEY (migration_quarantine_id),
    CONSTRAINT fk_migration_quarantine_job
        FOREIGN KEY (migration_job_id) REFERENCES migration_jobs (migration_job_id) ON DELETE CASCADE
);

CREATE INDEX ix_quarantine_job_table
    ON migration_quarantine (migration_job_id, table_schema, table_name);

-- ── Validation ───────────────────────────────────────────────────────────────

CREATE TABLE validation_runs (
    validation_run_id   VARCHAR(36) NOT NULL,
    migration_job_id    VARCHAR(36) NOT NULL,
    level               INTEGER     NOT NULL,
    status              VARCHAR(20) NOT NULL,
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    pass_count          INTEGER     NOT NULL DEFAULT 0,
    fail_count          INTEGER     NOT NULL DEFAULT 0,
    report              JSONB,
    CONSTRAINT pk_validation_runs PRIMARY KEY (validation_run_id),
    CONSTRAINT fk_validation_runs_job
        FOREIGN KEY (migration_job_id) REFERENCES migration_jobs (migration_job_id) ON DELETE CASCADE
);

CREATE INDEX ix_validation_runs_migration_job_id ON validation_runs (migration_job_id);

CREATE TABLE validation_mismatches (
    validation_mismatch_id  VARCHAR(36)  NOT NULL,
    validation_run_id       VARCHAR(36)  NOT NULL,
    table_schema            VARCHAR(255),
    table_name              VARCHAR(255),
    mismatch_type           VARCHAR(50),
    source_value            TEXT,
    target_value            TEXT,
    details                 JSONB,
    created_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT pk_validation_mismatches PRIMARY KEY (validation_mismatch_id),
    CONSTRAINT fk_validation_mismatches_run
        FOREIGN KEY (validation_run_id) REFERENCES validation_runs (validation_run_id) ON DELETE CASCADE
);

CREATE INDEX ix_validation_mismatches_validation_run_id ON validation_mismatches (validation_run_id);

-- ── Audit & cutover ──────────────────────────────────────────────────────────

CREATE TABLE audit_log (
    audit_log_id    VARCHAR(36)  NOT NULL,
    timestamp       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    action          VARCHAR(64)  NOT NULL,
    actor           VARCHAR(255) NOT NULL,
    resource        VARCHAR(512) NOT NULL,
    details         JSONB,
    correlation_id  VARCHAR(64),
    source_ip       VARCHAR(64),
    project_id      VARCHAR(36),
    success         BOOLEAN      NOT NULL DEFAULT TRUE,
    error_message   TEXT,
    CONSTRAINT pk_audit_log PRIMARY KEY (audit_log_id)
);

CREATE INDEX ix_audit_log_timestamp ON audit_log (timestamp);
CREATE INDEX ix_audit_log_action ON audit_log (action);
CREATE INDEX ix_audit_log_actor ON audit_log (actor);
CREATE INDEX ix_audit_log_resource ON audit_log (resource);
CREATE INDEX ix_audit_log_project_id ON audit_log (project_id);

CREATE TABLE cutover_checkpoints (
    cutover_checkpoint_id   VARCHAR(36)  NOT NULL,
    migration_job_id        VARCHAR(36)  NOT NULL,
    tables                  JSONB        NOT NULL,
    schema_name             VARCHAR(255) NOT NULL DEFAULT 'dbo',
    target_schema           VARCHAR(255) NOT NULL DEFAULT 'public',
    checkpoint_lsn          VARCHAR(64),
    row_counts              JSONB,
    snapshot_ref            VARCHAR(512),
    committed               BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    committed_at            TIMESTAMPTZ,
    rolled_back_at          TIMESTAMPTZ,
    writes_frozen_at        TIMESTAMPTZ,
    source_row_counts       JSONB,
    connection_switch       JSONB,
    CONSTRAINT pk_cutover_checkpoints PRIMARY KEY (cutover_checkpoint_id)
);

CREATE INDEX ix_cutover_checkpoints_migration_job_id ON cutover_checkpoints (migration_job_id);

-- ── Replication ──────────────────────────────────────────────────────────────

CREATE TABLE replication_streams (
    replication_stream_id   VARCHAR(36)  NOT NULL,
    project_connection_id   VARCHAR(36),
    status                  VARCHAR(32)  NOT NULL DEFAULT 'IDLE',
    last_checkpoint_lsn     VARCHAR(64),
    error_message           TEXT,
    started_at              TIMESTAMPTZ,
    stopped_at              TIMESTAMPTZ,
    created_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT pk_replication_streams PRIMARY KEY (replication_stream_id),
    CONSTRAINT fk_replication_streams_connection
        FOREIGN KEY (project_connection_id)
        REFERENCES project_connections (project_connection_id) ON DELETE SET NULL
);

CREATE INDEX ix_replication_streams_status ON replication_streams (status);
CREATE INDEX ix_replication_streams_project_connection_id ON replication_streams (project_connection_id);

-- ── Programs & waves ─────────────────────────────────────────────────────────

CREATE TABLE migration_programs (
    migration_program_id    VARCHAR(36)  NOT NULL,
    project_id              VARCHAR(36)  NOT NULL,
    name                    VARCHAR(255) NOT NULL,
    status                  VARCHAR(32)  NOT NULL DEFAULT 'planning',
    owner                   VARCHAR(255),
    notes                   TEXT,
    created_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT pk_migration_programs PRIMARY KEY (migration_program_id),
    CONSTRAINT fk_migration_programs_project
        FOREIGN KEY (project_id) REFERENCES project_projects (project_id) ON DELETE CASCADE
);

CREATE INDEX ix_migration_programs_project_id ON migration_programs (project_id);
CREATE INDEX ix_migration_programs_status ON migration_programs (status);

CREATE TABLE migration_waves (
    migration_wave_id       VARCHAR(36)  NOT NULL,
    migration_program_id    VARCHAR(36)  NOT NULL,
    wave_number             INTEGER      NOT NULL DEFAULT 1,
    name                    VARCHAR(255) NOT NULL,
    tables                  JSONB        NOT NULL DEFAULT '[]'::jsonb,
    schema_name             VARCHAR(255) NOT NULL DEFAULT 'dbo',
    status                  VARCHAR(32)  NOT NULL DEFAULT 'pending',
    cutover_window_start    TIMESTAMPTZ,
    cutover_window_end      TIMESTAMPTZ,
    approver                VARCHAR(255),
    signed_off_at           TIMESTAMPTZ,
    migration_job_id        VARCHAR(36),
    created_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT pk_migration_waves PRIMARY KEY (migration_wave_id),
    CONSTRAINT fk_migration_waves_program
        FOREIGN KEY (migration_program_id)
        REFERENCES migration_programs (migration_program_id) ON DELETE CASCADE
);

CREATE INDEX ix_migration_waves_migration_program_id ON migration_waves (migration_program_id);
CREATE INDEX ix_migration_waves_program_number ON migration_waves (migration_program_id, wave_number);
CREATE INDEX ix_migration_waves_status ON migration_waves (status);
CREATE INDEX ix_migration_waves_migration_job_id ON migration_waves (migration_job_id);

COMMIT;
