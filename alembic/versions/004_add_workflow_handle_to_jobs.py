# Author: Ravi Sharma
# Copyright (c) 2026 Ravi Sharma
# SPDX-License-Identifier: MIT
"""Add workflow_handle_id to migration_jobs for Temporal bridge (L-9)

Revision ID: 004
Revises: 003
Create Date: 2026-06-01

Adds an optional ``workflow_handle_id`` column to ``migration_jobs``.
NULL = job is controlled by the REST API (asyncio background task).
Non-NULL = job was submitted to Temporal; the value is the Temporal workflow
execution ID, used by WorkflowBridgeService to poll for status.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "migration_jobs",
        sa.Column("workflow_handle_id", sa.String(255), nullable=True),
    )
    op.create_index(
        "ix_migration_jobs_workflow_handle",
        "migration_jobs",
        ["workflow_handle_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_migration_jobs_workflow_handle", table_name="migration_jobs")
    op.drop_column("migration_jobs", "workflow_handle_id")
