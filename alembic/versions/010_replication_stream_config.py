"""
Module: 010_replication_stream_config.py
Purpose: Extend replication_streams with config, concerns, and metrics columns
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_column_if_missing(table: str, column: str, col_type: sa.types.TypeEngine) -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return
    existing = {c["name"] for c in insp.get_columns(table)}
    if column not in existing:
        op.add_column(table, sa.Column(column, col_type, nullable=True))


def upgrade() -> None:
    _add_column_if_missing("replication_streams", "target_project_connection_id", sa.String(36))
    _add_column_if_missing("replication_streams", "stream_name", sa.String(255))
    _add_column_if_missing("replication_streams", "config_json", sa.JSON())
    _add_column_if_missing("replication_streams", "concerns_json", sa.JSON())
    _add_column_if_missing("replication_streams", "events_captured", sa.Integer())
    _add_column_if_missing("replication_streams", "events_applied", sa.Integer())


def downgrade() -> None:
    for col in (
        "events_applied",
        "events_captured",
        "concerns_json",
        "config_json",
        "stream_name",
        "target_project_connection_id",
    ):
        try:
            op.drop_column("replication_streams", col)
        except Exception:
            pass
