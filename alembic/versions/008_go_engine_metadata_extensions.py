# Author: Ravi Sharma
# Copyright (c) 2026 Ravi Sharma
# SPDX-License-Identifier: MIT
"""Go engine metadata extensions — job logs, worker heartbeats, table plan fields.

Revision ID: 008
Revises: 007
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "008"
down_revision: str | None = "007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    return name in sa.inspect(bind).get_table_names()


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns(table)}
    return column in cols


def _index_exists(table: str, index: str) -> bool:
    bind = op.get_bind()
    indexes = sa.inspect(bind).get_indexes(table)
    return any(idx.get("name") == index for idx in indexes)


def upgrade() -> None:
    if _table_exists("migration_jobs") and not _column_exists("migration_jobs", "executor"):
        op.add_column(
            "migration_jobs",
            sa.Column("executor", sa.String(20), nullable=False, server_default="go"),
        )

    if _table_exists("migration_table_plans"):
        if not _column_exists("migration_table_plans", "target_schema"):
            op.add_column(
                "migration_table_plans",
                sa.Column("target_schema", sa.String(255), nullable=False, server_default="public"),
            )
        if not _column_exists("migration_table_plans", "columns"):
            op.add_column(
                "migration_table_plans",
                sa.Column("columns", sa.JSON(), nullable=True),
            )
        if not _column_exists("migration_table_plans", "plan_config"):
            op.add_column(
                "migration_table_plans",
                sa.Column("plan_config", sa.JSON(), nullable=True),
            )

    if not _table_exists("migration_job_logs"):
        op.create_table(
            "migration_job_logs",
            sa.Column("migration_job_log_id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("migration_job_id", sa.String(36), nullable=False),
            sa.Column("logged_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("level", sa.String(20), nullable=False, server_default="info"),
            sa.Column("message", sa.Text(), nullable=False),
            sa.PrimaryKeyConstraint("migration_job_log_id", name="pk_migration_job_logs"),
            sa.ForeignKeyConstraint(
                ["migration_job_id"],
                ["migration_jobs.migration_job_id"],
                name="fk_migration_job_logs_job",
                ondelete="CASCADE",
            ),
        )
    if _table_exists("migration_job_logs") and not _index_exists(
        "migration_job_logs", "ix_migration_job_logs_job_time"
    ):
        op.create_index(
            "ix_migration_job_logs_job_time",
            "migration_job_logs",
            ["migration_job_id", "logged_at"],
        )

    if not _table_exists("migration_worker_heartbeats"):
        op.create_table(
            "migration_worker_heartbeats",
            sa.Column("worker_id", sa.String(128), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("engine_version", sa.String(32), nullable=False, server_default="0.2.0"),
            sa.Column("status", sa.String(32), nullable=False, server_default="idle"),
            sa.PrimaryKeyConstraint("worker_id", name="pk_migration_worker_heartbeats"),
        )


def downgrade() -> None:
    op.drop_table("migration_worker_heartbeats")
    op.drop_index("ix_migration_job_logs_job_time", table_name="migration_job_logs")
    op.drop_table("migration_job_logs")
    op.drop_column("migration_table_plans", "plan_config")
    op.drop_column("migration_table_plans", "columns")
    op.drop_column("migration_table_plans", "target_schema")
    op.drop_column("migration_jobs", "executor")
