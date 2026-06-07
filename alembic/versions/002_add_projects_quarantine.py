"""Add project_projects and migration_quarantine tables

Revision ID: 002
Revises: 001
Create Date: 2026-05-31
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_projects",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_connection_id", sa.String(36), nullable=True),
        sa.Column("target_connection_id", sa.String(36), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_connection_id"],
            ["project_connections.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["target_connection_id"],
            ["project_connections.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["auth_users.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_project_projects_name"),
    )
    op.create_index("ix_project_projects_name", "project_projects", ["name"])
    op.create_index(
        "ix_project_projects_src_conn",
        "project_projects",
        ["source_connection_id"],
    )
    op.create_index(
        "ix_project_projects_tgt_conn",
        "project_projects",
        ["target_connection_id"],
    )

    op.create_table(
        "migration_quarantine",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("table_schema", sa.String(255), nullable=True),
        sa.Column("table_name", sa.String(255), nullable=True),
        sa.Column("row_pk_value", sa.Text(), nullable=True),
        sa.Column("error_column", sa.String(255), nullable=True),
        sa.Column("error_type", sa.String(100), nullable=True),
        sa.Column("source_value", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["migration_jobs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_quarantine_job_table",
        "migration_quarantine",
        ["job_id", "table_schema", "table_name"],
    )


def downgrade() -> None:
    op.drop_index("ix_quarantine_job_table", table_name="migration_quarantine")
    op.drop_table("migration_quarantine")
    op.drop_index("ix_project_projects_tgt_conn", table_name="project_projects")
    op.drop_index("ix_project_projects_src_conn", table_name="project_projects")
    op.drop_index("ix_project_projects_name", table_name="project_projects")
    op.drop_table("project_projects")
