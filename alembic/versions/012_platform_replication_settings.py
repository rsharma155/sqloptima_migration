"""
Module: 012_platform_replication_settings.py
Purpose: Platform-wide replication CDC poll interval and batch size
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(name: str) -> bool:
    bind = op.get_bind()
    return name in sa.inspect(bind).get_table_names()


def upgrade() -> None:
    if _table_exists("platform_replication_settings"):
        return
    op.create_table(
        "platform_replication_settings",
        sa.Column("settings_id", sa.String(36), primary_key=True),
        sa.Column("poll_interval_ms", sa.Integer(), nullable=False, server_default="1000"),
        sa.Column("batch_size", sa.Integer(), nullable=False, server_default="1000"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )


def downgrade() -> None:
    if _table_exists("platform_replication_settings"):
        op.drop_table("platform_replication_settings")
