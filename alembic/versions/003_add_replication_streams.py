# Author: Ravi Sharma
# Copyright (c) 2026 Ravi Sharma
# SPDX-License-Identifier: MIT
"""Add replication_streams table for CDC stream lifecycle tracking (L-11)

Revision ID: 003
Revises: 002
Create Date: 2026-06-01

Adds the ``replication_streams`` table to the platform metadata database.
Each row tracks a single CDC / incremental replication session including its
9-state lifecycle status and the last applied LSN (mirrored from the target DB
``_replication_checkpoint`` table for dashboard visibility).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "replication_streams",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("connection_id", sa.String(36), nullable=True),
        # 9-state machine values:
        # IDLE | STARTING | SNAPSHOTTING | CDC_CATCHUP | CDC_STREAMING
        # PAUSED | STOPPING | FAILED | COMPLETED
        sa.Column("status", sa.String(32), nullable=False, server_default="IDLE"),
        sa.Column("last_checkpoint_lsn", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["project_connections.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_replication_streams_status",
        "replication_streams",
        ["status"],
    )
    op.create_index(
        "ix_replication_streams_connection_id",
        "replication_streams",
        ["connection_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_replication_streams_connection_id", table_name="replication_streams")
    op.drop_index("ix_replication_streams_status", table_name="replication_streams")
    op.drop_table("replication_streams")
