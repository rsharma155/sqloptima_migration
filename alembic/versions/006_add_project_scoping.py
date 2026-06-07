# Author: Ravi Sharma
# Copyright (c) 2026 Ravi Sharma
# SPDX-License-Identifier: MIT
"""Add project_id scoping columns (§13.7)

Revision ID: 006
Revises: 005
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "project_connections",
        sa.Column("project_id", sa.String(36), nullable=True),
    )
    op.create_index("ix_project_connections_project_id", "project_connections", ["project_id"])
    op.create_foreign_key(
        "fk_connections_project",
        "project_connections",
        "project_projects",
        ["project_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "migration_jobs",
        sa.Column("project_id", sa.String(36), nullable=True),
    )
    op.create_index("ix_migration_jobs_project_id", "migration_jobs", ["project_id"])

    op.add_column(
        "audit_log",
        sa.Column("project_id", sa.String(36), nullable=True),
    )
    op.create_index("ix_audit_log_project_id", "audit_log", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_project_id", "audit_log")
    op.drop_column("audit_log", "project_id")
    op.drop_index("ix_migration_jobs_project_id", "migration_jobs")
    op.drop_column("migration_jobs", "project_id")
    op.drop_constraint("fk_connections_project", "project_connections", type_="foreignkey")
    op.drop_index("ix_project_connections_project_id", "project_connections")
    op.drop_column("project_connections", "project_id")
