"""
Module: 014_platform_transfer_settings.py
Purpose: Platform Transfer file-offload settings + per-table error columns
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    return name in sa.inspect(bind).get_table_names()


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns(table)}
    return column in cols


def _index_exists(table: str, name: str) -> bool:
    bind = op.get_bind()
    if table not in sa.inspect(bind).get_table_names():
        return False
    return any(idx["name"] == name for idx in sa.inspect(bind).get_indexes(table))


def upgrade() -> None:
    if not _table_exists("platform_transfer_settings"):
        op.create_table(
            "platform_transfer_settings",
            sa.Column("settings_id", sa.String(36), primary_key=True),
            sa.Column("file_offload_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column(
                "file_offload_min_rows",
                sa.BigInteger(),
                nullable=False,
                server_default="2000000",
            ),
            sa.Column(
                "file_offload_min_mb",
                sa.Float(),
                nullable=False,
                server_default="256.0",
            ),
            sa.Column("staging_path", sa.String(1024), nullable=False, server_default=""),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
        )

    if _table_exists("transfer_table_plans"):
        if not _column_exists("transfer_table_plans", "error"):
            op.add_column("transfer_table_plans", sa.Column("error", sa.Text(), nullable=True))
        if not _column_exists("transfer_table_plans", "error_at"):
            op.add_column(
                "transfer_table_plans",
                sa.Column("error_at", sa.DateTime(timezone=True), nullable=True),
            )
        if not _column_exists("transfer_table_plans", "error_count"):
            op.add_column(
                "transfer_table_plans",
                sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
            )

    if _table_exists("transfer_job_logs") and not _index_exists(
        "transfer_job_logs", "ix_transfer_job_logs_job_table"
    ):
        op.create_index(
            "ix_transfer_job_logs_job_table",
            "transfer_job_logs",
            ["transfer_job_id", "table_name", "logged_at"],
        )


def downgrade() -> None:
    if _table_exists("transfer_job_logs") and _index_exists(
        "transfer_job_logs", "ix_transfer_job_logs_job_table"
    ):
        op.drop_index("ix_transfer_job_logs_job_table", table_name="transfer_job_logs")
    if _table_exists("transfer_table_plans"):
        for column in ("error_count", "error_at", "error"):
            if _column_exists("transfer_table_plans", column):
                op.drop_column("transfer_table_plans", column)
    if _table_exists("platform_transfer_settings"):
        op.drop_table("platform_transfer_settings")
