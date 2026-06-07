"""Initial schema — platform metadata tables

Revision ID: 001
Revises:
Create Date: 2026-05-30
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # project_connections — source and target DB profiles with encrypted passwords.
    op.create_table(
        "project_connections",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("db_type", sa.String(20), nullable=False),
        sa.Column("host", sa.String(255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("database_name", sa.String(255), nullable=False),
        sa.Column("username", sa.String(255), nullable=False),
        sa.Column("encrypted_password", sa.Text(), nullable=False),
        sa.Column("ssl_enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_test_ok", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    # migration_jobs — one row per migration run.
    op.create_table(
        "migration_jobs",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("source_connection_id", sa.String(36), nullable=True),
        sa.Column("target_connection_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("tables_total", sa.Integer(), nullable=False),
        sa.Column("tables_done", sa.Integer(), nullable=False),
        sa.Column("rows_total", sa.BigInteger(), nullable=False),
        sa.Column("rows_migrated", sa.BigInteger(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_connection_id"], ["project_connections.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["target_connection_id"], ["project_connections.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_migration_jobs_status", "migration_jobs", ["status"])
    op.create_index("ix_migration_jobs_src", "migration_jobs", ["source_connection_id"])
    op.create_index("ix_migration_jobs_tgt", "migration_jobs", ["target_connection_id"])

    # migration_table_plans — one row per table within a job.
    op.create_table(
        "migration_table_plans",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("table_name", sa.String(255), nullable=False),
        sa.Column("schema_name", sa.String(255), nullable=False),
        sa.Column("strategy", sa.String(50), nullable=False),
        sa.Column("chunk_size", sa.Integer(), nullable=False),
        sa.Column("parallel_workers", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("rows_migrated", sa.BigInteger(), nullable=False),
        sa.Column("row_count_estimate", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["migration_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_table_plans_job_table", "migration_table_plans", ["job_id", "table_name"])

    # migration_commands — pause/resume/stop signals from API to worker.
    op.create_table(
        "migration_commands",
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("command", sa.String(20), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["migration_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("job_id"),
    )

    # validation_runs — L1–L4 validation results.
    op.create_table(
        "validation_runs",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pass_count", sa.Integer(), nullable=False),
        sa.Column("fail_count", sa.Integer(), nullable=False),
        sa.Column("report", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["migration_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_validation_runs_job_id", "validation_runs", ["job_id"])

    # validation_mismatches — row-level discrepancies found during validation.
    op.create_table(
        "validation_mismatches",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("table_schema", sa.String(255), nullable=True),
        sa.Column("table_name", sa.String(255), nullable=True),
        sa.Column("mismatch_type", sa.String(50), nullable=True),
        sa.Column("source_value", sa.Text(), nullable=True),
        sa.Column("target_value", sa.Text(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["validation_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_validation_mismatches_run_id", "validation_mismatches", ["run_id"])


def downgrade() -> None:
    op.drop_table("validation_mismatches")
    op.drop_table("validation_runs")
    op.drop_table("migration_commands")
    op.drop_table("migration_table_plans")
    op.drop_table("migration_jobs")
    op.drop_table("project_connections")
