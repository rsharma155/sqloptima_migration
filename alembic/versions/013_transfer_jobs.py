"""
Module: 013_transfer_jobs.py
Purpose: Connection engine column + Cross-Database Transfer tables
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    return name in sa.inspect(bind).get_table_names()


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns(table)}
    return column in cols


def upgrade() -> None:
    if _table_exists("project_connections") and not _column_exists("project_connections", "engine"):
        op.add_column("project_connections", sa.Column("engine", sa.String(20), nullable=True))
        op.execute(
            sa.text(
                "UPDATE project_connections SET engine = CASE "
                "WHEN db_type = 'target' THEN 'postgres' "
                "ELSE 'sqlserver' END "
                "WHERE engine IS NULL"
            )
        )

    if not _table_exists("transfer_jobs"):
        op.create_table(
            "transfer_jobs",
            sa.Column("transfer_job_id", sa.String(36), primary_key=True),
            sa.Column("path", sa.String(32), nullable=False),
            sa.Column("source_project_connection_id", sa.String(36), nullable=True),
            sa.Column("target_project_connection_id", sa.String(36), nullable=True),
            sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
            sa.Column("phase", sa.String(32), nullable=False, server_default="idle"),
            sa.Column("tables_total", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("tables_done", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("rows_total", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("rows_copied", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("preflight_json", sa.JSON(), nullable=True),
            sa.Column("constraint_plan", sa.JSON(), nullable=True),
            sa.Column("config", sa.JSON(), nullable=True),
            sa.Column("project_id", sa.String(36), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["source_project_connection_id"],
                ["project_connections.project_connection_id"],
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["target_project_connection_id"],
                ["project_connections.project_connection_id"],
                ondelete="SET NULL",
            ),
        )
        op.create_index("ix_transfer_jobs_status", "transfer_jobs", ["status"])
        op.create_index("ix_transfer_jobs_project_id", "transfer_jobs", ["project_id"])

    if not _table_exists("transfer_table_plans"):
        op.create_table(
            "transfer_table_plans",
            sa.Column("transfer_table_plan_id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("transfer_job_id", sa.String(36), nullable=False),
            sa.Column("source_schema", sa.String(255), nullable=False),
            sa.Column("source_table", sa.String(255), nullable=False),
            sa.Column("target_schema", sa.String(255), nullable=False),
            sa.Column("target_table", sa.String(255), nullable=False),
            sa.Column("chunk_size", sa.Integer(), nullable=False, server_default="10000"),
            sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
            sa.Column("rows_copied", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("row_count_estimate", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("columns", sa.JSON(), nullable=True),
            sa.ForeignKeyConstraint(
                ["transfer_job_id"],
                ["transfer_jobs.transfer_job_id"],
                ondelete="CASCADE",
            ),
        )
        op.create_index(
            "ix_transfer_plans_job_table",
            "transfer_table_plans",
            ["transfer_job_id", "source_table"],
        )

    if not _table_exists("transfer_commands"):
        op.create_table(
            "transfer_commands",
            sa.Column("transfer_job_id", sa.String(36), primary_key=True),
            sa.Column("command", sa.String(20), nullable=False),
            sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("acked_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(
                ["transfer_job_id"],
                ["transfer_jobs.transfer_job_id"],
                ondelete="CASCADE",
            ),
        )

    if not _table_exists("transfer_runtime_settings"):
        op.create_table(
            "transfer_runtime_settings",
            sa.Column("transfer_job_id", sa.String(36), primary_key=True),
            sa.Column("chunk_size", sa.Integer(), nullable=False, server_default="10000"),
            sa.Column("min_chunk_size", sa.Integer(), nullable=False, server_default="1000"),
            sa.Column("max_chunk_size", sa.Integer(), nullable=False, server_default="100000"),
            sa.Column("max_rows_per_sec", sa.Integer(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["transfer_job_id"],
                ["transfer_jobs.transfer_job_id"],
                ondelete="CASCADE",
            ),
        )

    if not _table_exists("transfer_job_logs"):
        op.create_table(
            "transfer_job_logs",
            sa.Column("transfer_job_log_id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("transfer_job_id", sa.String(36), nullable=False),
            sa.Column("logged_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("level", sa.String(20), nullable=False, server_default="info"),
            sa.Column("phase", sa.String(32), nullable=True),
            sa.Column("table_name", sa.String(255), nullable=True),
            sa.Column("message", sa.Text(), nullable=False),
            sa.ForeignKeyConstraint(
                ["transfer_job_id"],
                ["transfer_jobs.transfer_job_id"],
                ondelete="CASCADE",
            ),
        )
        op.create_index(
            "ix_transfer_job_logs_job_time",
            "transfer_job_logs",
            ["transfer_job_id", "logged_at"],
        )

    if not _table_exists("transfer_constraint_actions"):
        op.create_table(
            "transfer_constraint_actions",
            sa.Column("transfer_constraint_action_id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("transfer_job_id", sa.String(36), nullable=False),
            sa.Column("table_name", sa.String(255), nullable=False),
            sa.Column("object_id", sa.String(255), nullable=False),
            sa.Column("object_kind", sa.String(50), nullable=False),
            sa.Column("planned_action", sa.String(32), nullable=False),
            sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("restored_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("status", sa.String(32), nullable=False, server_default="planned"),
            sa.Column("message", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(
                ["transfer_job_id"],
                ["transfer_jobs.transfer_job_id"],
                ondelete="CASCADE",
            ),
        )


def downgrade() -> None:
    for name in (
        "transfer_constraint_actions",
        "transfer_job_logs",
        "transfer_runtime_settings",
        "transfer_commands",
        "transfer_table_plans",
        "transfer_jobs",
    ):
        if _table_exists(name):
            op.drop_table(name)
    if _table_exists("project_connections") and _column_exists("project_connections", "engine"):
        op.drop_column("project_connections", "engine")
