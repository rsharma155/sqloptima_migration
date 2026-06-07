# Author: Ravi Sharma
# Copyright (c) 2026 Ravi Sharma
# SPDX-License-Identifier: MIT
"""Add vault_ref to project_connections for external secret manager support

Revision ID: 005
Revises: 004
Create Date: 2026-06-05

Adds an optional ``vault_ref`` column to ``project_connections``.
NULL = use the existing Fernet-encrypted ``encrypted_password`` field.
Non-NULL = resolve the secret at runtime via the configured SECRET_PROVIDER
           (HashiCorp Vault, AWS Secrets Manager, Azure Key Vault, GCP Secret Manager).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "project_connections",
        sa.Column("vault_ref", sa.String(512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("project_connections", "vault_ref")
