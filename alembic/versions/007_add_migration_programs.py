# Author: Ravi Sharma
# Copyright (c) 2026 Ravi Sharma
# SPDX-License-Identifier: MIT
"""Add migration_programs and migration_waves tables (§13.1)

Revision ID: 007
Revises: 006
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "migration_programs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("project_projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="planning"),
        sa.Column("owner", sa.String(255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_migration_programs_project_id", "migration_programs", ["project_id"])

    op.create_table(
        "migration_waves",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("program_id", sa.String(36), sa.ForeignKey("migration_programs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("wave_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("tables", sa.JSON(), nullable=False),
        sa.Column("schema_name", sa.String(255), nullable=False, server_default="dbo"),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("cutover_window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cutover_window_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approver", sa.String(255), nullable=True),
        sa.Column("signed_off_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("job_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_migration_waves_program_id", "migration_waves", ["program_id"])


def downgrade() -> None:
    op.drop_table("migration_waves")
    op.drop_table("migration_programs")
