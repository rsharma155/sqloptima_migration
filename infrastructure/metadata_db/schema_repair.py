"""Idempotent metadata schema repair for Go-engine columns (Alembic 008/009).

When ``init_db`` runs ``create_all`` on an existing database, SQLAlchemy does not
add new columns to existing tables. A subsequent Alembic stamp to head can leave
the DB marked at revision 009 while ``migration_jobs.executor`` and related fields
are still missing. This module closes that gap on every startup.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import inspect


def _column_exists(conn: sa.Connection, table: str, column: str) -> bool:
    cols = {c["name"] for c in inspect(conn).get_columns(table)}
    return column in cols


def _table_exists(conn: sa.Connection, name: str) -> bool:
    return name in inspect(conn).get_table_names()


def repair_go_engine_metadata(conn: sa.Connection) -> None:
    """Add 008/009 columns when Alembic stamped head without executing migrations."""
    if _table_exists(conn, "migration_jobs") and not _column_exists(conn, "migration_jobs", "executor"):
        conn.execute(
            sa.text(
                "ALTER TABLE migration_jobs "
                "ADD COLUMN executor VARCHAR(20) NOT NULL DEFAULT 'go'"
            )
        )

    if not _table_exists(conn, "migration_table_plans"):
        return

    if not _column_exists(conn, "migration_table_plans", "target_schema"):
        conn.execute(
            sa.text(
                "ALTER TABLE migration_table_plans "
                "ADD COLUMN target_schema VARCHAR(255) NOT NULL DEFAULT 'public'"
            )
        )
    if not _column_exists(conn, "migration_table_plans", "columns"):
        conn.execute(sa.text("ALTER TABLE migration_table_plans ADD COLUMN columns JSON"))
    if not _column_exists(conn, "migration_table_plans", "plan_config"):
        conn.execute(sa.text("ALTER TABLE migration_table_plans ADD COLUMN plan_config JSON"))


def repair_replication_stream_metadata(conn: sa.Connection) -> None:
    """Add replication_streams columns introduced in Alembic 010 when missing."""
    if not _table_exists(conn, "replication_streams"):
        return
    additions: list[tuple[str, str]] = [
        ("target_project_connection_id", "VARCHAR(36)"),
        ("stream_name", "VARCHAR(255)"),
        ("config_json", "JSON"),
        ("concerns_json", "JSON"),
        ("events_captured", "INTEGER NOT NULL DEFAULT 0"),
        ("events_applied", "INTEGER NOT NULL DEFAULT 0"),
    ]
    for column, ddl in additions:
        if not _column_exists(conn, "replication_streams", column):
            conn.execute(sa.text(f"ALTER TABLE replication_streams ADD COLUMN {column} {ddl}"))
