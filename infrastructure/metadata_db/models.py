"""SQLAlchemy ORM models for all platform metadata.

Table naming uses a flat prefix convention (auth_, project_, migration_, validation_) to
stay compatible with both SQLite (no schema support) and PostgreSQL. When the Rust engine
eventually needs direct DB access, these same tables are the shared contract.

Primary-key columns use table-specific names (e.g. migration_job_id) so joins and
application code stay unambiguous as the schema grows.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship

from sqlalchemy import JSON


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class UserRecord(Base):
    __tablename__ = "auth_users"

    auth_user_id = Column(String(36), primary_key=True)
    email = Column(String(255), nullable=False)
    username = Column(String(100), nullable=False)
    password_hash = Column(String(512), nullable=False)
    role = Column(String(20), nullable=False, default="viewer")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    last_login_at = Column(DateTime(timezone=True), nullable=True)

    sessions = relationship(
        "SessionRecord",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("email", name="uq_auth_users_email"),
        UniqueConstraint("username", name="uq_auth_users_username"),
        Index("ix_auth_users_email", "email"),
        Index("ix_auth_users_username", "username"),
    )


class SessionRecord(Base):
    __tablename__ = "auth_sessions"

    auth_session_id = Column(String(36), primary_key=True)
    auth_user_id = Column(
        String(36),
        ForeignKey("auth_users.auth_user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    refresh_token_hash = Column(String(512), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    user = relationship("UserRecord", back_populates="sessions")

    __table_args__ = (
        UniqueConstraint("refresh_token_hash", name="uq_sessions_token_hash"),
    )


class ConnectionRecord(Base):
    __tablename__ = "project_connections"

    project_connection_id = Column(String(36), primary_key=True)
    name = Column(String(255), nullable=False)
    db_type = Column(String(20), nullable=False)
    host = Column(String(255), nullable=False)
    port = Column(Integer, nullable=False)
    database_name = Column(String(255), nullable=False)
    username = Column(String(255), nullable=False)
    encrypted_password = Column(Text, nullable=False, default="")
    vault_ref = Column(String(512), nullable=True)
    ssl_enabled = Column(Boolean, nullable=False, default=False)
    project_id = Column(
        String(36),
        ForeignKey("project_projects.project_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    last_tested_at = Column(DateTime(timezone=True), nullable=True)
    last_test_ok = Column(Boolean, nullable=True)

    source_jobs = relationship(
        "MigrationJobRecord",
        foreign_keys="MigrationJobRecord.source_project_connection_id",
        back_populates="source_connection",
    )
    target_jobs = relationship(
        "MigrationJobRecord",
        foreign_keys="MigrationJobRecord.target_project_connection_id",
        back_populates="target_connection",
    )


class MigrationJobRecord(Base):
    __tablename__ = "migration_jobs"

    migration_job_id = Column(String(36), primary_key=True)
    source_project_connection_id = Column(
        String(36),
        ForeignKey("project_connections.project_connection_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    target_project_connection_id = Column(
        String(36),
        ForeignKey("project_connections.project_connection_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status = Column(String(20), nullable=False, default="PENDING", index=True)
    tables_total = Column(Integer, nullable=False, default=0)
    tables_done = Column(Integer, nullable=False, default=0)
    rows_total = Column(BigInteger, nullable=False, default=0)
    rows_migrated = Column(BigInteger, nullable=False, default=0)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error = Column(Text, nullable=True)
    config = Column(JSON, nullable=True)
    executor = Column(String(20), nullable=False, default="go")
    workflow_handle_id = Column(String(255), nullable=True, index=True)
    project_id = Column(String(36), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    source_connection = relationship(
        "ConnectionRecord",
        foreign_keys=[source_project_connection_id],
        back_populates="source_jobs",
    )
    target_connection = relationship(
        "ConnectionRecord",
        foreign_keys=[target_project_connection_id],
        back_populates="target_jobs",
    )
    table_plans = relationship(
        "MigrationTablePlanRecord",
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="MigrationTablePlanRecord.migration_table_plan_id",
    )
    command = relationship(
        "MigrationCommandRecord",
        back_populates="job",
        uselist=False,
        cascade="all, delete-orphan",
    )
    logs = relationship(
        "MigrationJobLogRecord",
        back_populates="job",
        cascade="all, delete-orphan",
        order_by="MigrationJobLogRecord.logged_at",
    )


class MigrationJobLogRecord(Base):
    __tablename__ = "migration_job_logs"

    migration_job_log_id = Column(Integer, primary_key=True, autoincrement=True)
    migration_job_id = Column(
        String(36),
        ForeignKey("migration_jobs.migration_job_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    logged_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    level = Column(String(20), nullable=False, default="info")
    message = Column(Text, nullable=False)

    job = relationship("MigrationJobRecord", back_populates="logs")

    __table_args__ = (
        Index("ix_migration_job_logs_job_time", "migration_job_id", "logged_at"),
    )


class MigrationWorkerHeartbeatRecord(Base):
    __tablename__ = "migration_worker_heartbeats"

    worker_id = Column(String(128), primary_key=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    engine_version = Column(String(32), nullable=False, default="0.2.0")
    status = Column(String(32), nullable=False, default="idle")


class MigrationTablePlanRecord(Base):
    __tablename__ = "migration_table_plans"

    migration_table_plan_id = Column(Integer, primary_key=True, autoincrement=True)
    migration_job_id = Column(
        String(36),
        ForeignKey("migration_jobs.migration_job_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    table_name = Column(String(255), nullable=False)
    schema_name = Column(String(255), nullable=False, default="dbo")
    target_schema = Column(String(255), nullable=False, default="public")
    strategy = Column(String(50), nullable=False, default="chunked")
    chunk_size = Column(Integer, nullable=False, default=10000)
    parallel_workers = Column(Integer, nullable=False, default=4)
    status = Column(String(50), nullable=False, default="pending")
    rows_migrated = Column(BigInteger, nullable=False, default=0)
    row_count_estimate = Column(BigInteger, nullable=False, default=0)
    columns = Column(JSON, nullable=True)
    plan_config = Column(JSON, nullable=True)

    job = relationship("MigrationJobRecord", back_populates="table_plans")

    __table_args__ = (
        Index("ix_table_plans_job_table", "migration_job_id", "table_name"),
    )


class MigrationCommandRecord(Base):
    __tablename__ = "migration_commands"

    migration_job_id = Column(
        String(36),
        ForeignKey("migration_jobs.migration_job_id", ondelete="CASCADE"),
        primary_key=True,
    )
    command = Column(String(20), nullable=False)
    issued_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    acked_at = Column(DateTime(timezone=True), nullable=True)

    job = relationship("MigrationJobRecord", back_populates="command")


class ValidationRunRecord(Base):
    __tablename__ = "validation_runs"

    validation_run_id = Column(String(36), primary_key=True)
    migration_job_id = Column(
        String(36),
        ForeignKey("migration_jobs.migration_job_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    level = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default="PENDING")
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    pass_count = Column(Integer, nullable=False, default=0)
    fail_count = Column(Integer, nullable=False, default=0)
    report = Column(JSON, nullable=True)

    mismatches = relationship(
        "ValidationMismatchRecord",
        back_populates="run",
        cascade="all, delete-orphan",
    )


class ValidationMismatchRecord(Base):
    __tablename__ = "validation_mismatches"

    validation_mismatch_id = Column(String(36), primary_key=True)
    validation_run_id = Column(
        String(36),
        ForeignKey("validation_runs.validation_run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    table_schema = Column(String(255), nullable=True)
    table_name = Column(String(255), nullable=True)
    mismatch_type = Column(String(50), nullable=True)
    source_value = Column(Text, nullable=True)
    target_value = Column(Text, nullable=True)
    details = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    run = relationship("ValidationRunRecord", back_populates="mismatches")


class ProjectRecord(Base):
    __tablename__ = "project_projects"

    project_id = Column(String(36), primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    source_project_connection_id = Column(
        String(36),
        ForeignKey("project_connections.project_connection_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    target_project_connection_id = Column(
        String(36),
        ForeignKey("project_connections.project_connection_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_by_auth_user_id = Column(
        String(36),
        ForeignKey("auth_users.auth_user_id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    source_connection = relationship(
        "ConnectionRecord",
        foreign_keys=[source_project_connection_id],
    )
    target_connection = relationship(
        "ConnectionRecord",
        foreign_keys=[target_project_connection_id],
    )

    __table_args__ = (
        UniqueConstraint("name", name="uq_project_projects_name"),
        Index("ix_project_projects_name", "name"),
    )


class QuarantineRecord(Base):
    __tablename__ = "migration_quarantine"

    migration_quarantine_id = Column(String(36), primary_key=True)
    migration_job_id = Column(
        String(36),
        ForeignKey("migration_jobs.migration_job_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    table_schema = Column(String(255), nullable=True)
    table_name = Column(String(255), nullable=True)
    row_pk_value = Column(Text, nullable=True)
    error_column = Column(String(255), nullable=True)
    error_type = Column(String(100), nullable=True)
    source_value = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    __table_args__ = (
        Index("ix_quarantine_job_table", "migration_job_id", "table_schema", "table_name"),
    )


class AuditLogRecord(Base):
    __tablename__ = "audit_log"

    audit_log_id = Column(String(36), primary_key=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, default=_now, index=True)
    action = Column(String(64), nullable=False, index=True)
    actor = Column(String(255), nullable=False, index=True)
    resource = Column(String(512), nullable=False, index=True)
    details = Column(JSON, nullable=True)
    correlation_id = Column(String(64), nullable=True)
    source_ip = Column(String(64), nullable=True)
    project_id = Column(String(36), nullable=True, index=True)
    success = Column(Boolean, nullable=False, default=True)
    error_message = Column(Text, nullable=True)


class TokenDenylistRecord(Base):
    __tablename__ = "auth_token_denylist"

    jti = Column(String(36), primary_key=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at = Column(DateTime(timezone=True), nullable=False, default=_now)


class CutoverCheckpointRecord(Base):
    __tablename__ = "cutover_checkpoints"

    cutover_checkpoint_id = Column(String(36), primary_key=True)
    migration_job_id = Column(String(36), nullable=False, index=True)
    tables = Column(JSON, nullable=False)
    schema_name = Column(String(255), nullable=False, default="dbo")
    target_schema = Column(String(255), nullable=False, default="public")
    checkpoint_lsn = Column(String(64), nullable=True)
    row_counts = Column(JSON, nullable=True)
    snapshot_ref = Column(String(512), nullable=True)
    committed = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    committed_at = Column(DateTime(timezone=True), nullable=True)
    rolled_back_at = Column(DateTime(timezone=True), nullable=True)
    writes_frozen_at = Column(DateTime(timezone=True), nullable=True)
    source_row_counts = Column(JSON, nullable=True)
    connection_switch = Column(JSON, nullable=True)


class MigrationProgramRecord(Base):
    __tablename__ = "migration_programs"

    migration_program_id = Column(String(36), primary_key=True)
    project_id = Column(
        String(36),
        ForeignKey("project_projects.project_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(255), nullable=False)
    status = Column(String(32), nullable=False, default="planning", index=True)
    owner = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    waves = relationship(
        "MigrationWaveRecord",
        back_populates="program",
        cascade="all, delete-orphan",
    )


class MigrationWaveRecord(Base):
    __tablename__ = "migration_waves"

    migration_wave_id = Column(String(36), primary_key=True)
    migration_program_id = Column(
        String(36),
        ForeignKey("migration_programs.migration_program_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    wave_number = Column(Integer, nullable=False, default=1)
    name = Column(String(255), nullable=False)
    tables = Column(JSON, nullable=False, default=list)
    schema_name = Column(String(255), nullable=False, default="dbo")
    status = Column(String(32), nullable=False, default="pending", index=True)
    cutover_window_start = Column(DateTime(timezone=True), nullable=True)
    cutover_window_end = Column(DateTime(timezone=True), nullable=True)
    approver = Column(String(255), nullable=True)
    signed_off_at = Column(DateTime(timezone=True), nullable=True)
    migration_job_id = Column(String(36), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    program = relationship("MigrationProgramRecord", back_populates="waves")

    __table_args__ = (
        Index("ix_migration_waves_program_number", "migration_program_id", "wave_number"),
    )


class PlatformMigrationSettingsRecord(Base):
    __tablename__ = "platform_migration_settings"

    settings_id = Column(String(36), primary_key=True, default="platform-default")
    source_throttle_enabled = Column(Boolean, nullable=False, default=True)
    small_table_delay_sec = Column(Float, nullable=False, default=1.0)
    large_table_delay_sec = Column(Float, nullable=False, default=4.0)
    large_table_row_threshold = Column(Integer, nullable=False, default=100_000)
    large_table_size_mb_threshold = Column(Float, nullable=False, default=50.0)
    max_tables_per_job = Column(Integer, nullable=False, default=25)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)


class PlatformReplicationSettingsRecord(Base):
    __tablename__ = "platform_replication_settings"

    settings_id = Column(String(36), primary_key=True, default="platform-default")
    poll_interval_ms = Column(Integer, nullable=False, default=1000)
    batch_size = Column(Integer, nullable=False, default=1000)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)


class PlatformNotificationSettingsRecord(Base):
    __tablename__ = "platform_notification_settings"

    settings_id = Column(String(36), primary_key=True, default="platform-default")
    webhook_enabled = Column(Boolean, nullable=False, default=False)
    webhook_url_encrypted = Column(Text, nullable=False, default="")
    email_enabled = Column(Boolean, nullable=False, default=False)
    smtp_host = Column(String(255), nullable=False, default="")
    smtp_port = Column(Integer, nullable=False, default=587)
    smtp_user = Column(String(255), nullable=False, default="")
    smtp_password_encrypted = Column(Text, nullable=False, default="")
    alert_email_to = Column(String(255), nullable=False, default="")
    alert_email_from = Column(String(255), nullable=False, default="")
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)


class ReplicationStreamRecord(Base):
    __tablename__ = "replication_streams"

    replication_stream_id = Column(String(36), primary_key=True)
    project_connection_id = Column(
        String(36),
        ForeignKey("project_connections.project_connection_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    target_project_connection_id = Column(String(36), nullable=True, index=True)
    stream_name = Column(String(255), nullable=True)
    status = Column(String(32), nullable=False, default="IDLE", index=True)
    last_checkpoint_lsn = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)
    config_json = Column(JSON, nullable=True)
    concerns_json = Column(JSON, nullable=True)
    events_captured = Column(Integer, nullable=False, default=0)
    events_applied = Column(Integer, nullable=False, default=0)
    started_at = Column(DateTime(timezone=True), nullable=True)
    stopped_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
