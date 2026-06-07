"""
Module: 011_platform_migration_settings.py
Purpose: Platform-wide migration throttle and job limits
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    return name in sa.inspect(bind).get_table_names()


def upgrade() -> None:
    # init_db runs create_all before Alembic on existing databases, so the table
    # may already exist when this revision is applied.
    if _table_exists("platform_migration_settings"):
        return
    op.create_table(
        "platform_migration_settings",
        sa.Column("settings_id", sa.String(36), primary_key=True),
        sa.Column("source_throttle_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("small_table_delay_sec", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("large_table_delay_sec", sa.Float(), nullable=False, server_default="4.0"),
        sa.Column("large_table_row_threshold", sa.Integer(), nullable=False, server_default="100000"),
        sa.Column("large_table_size_mb_threshold", sa.Float(), nullable=False, server_default="50.0"),
        sa.Column("max_tables_per_job", sa.Integer(), nullable=False, server_default="25"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )


def downgrade() -> None:
    if _table_exists("platform_migration_settings"):
        op.drop_table("platform_migration_settings")
