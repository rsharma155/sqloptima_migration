"""Async SQLAlchemy engine and session factory for the platform metadata store.

METADATA_DB_URL controls the backend:
  - (default) sqlite+aiosqlite:///migration_platform.db  — zero-config local dev
  - postgresql+asyncpg://user:pass@host:port/db_name     — production / multi-node

Plain "postgresql://" URLs are auto-rewritten to use the asyncpg driver.
Plain "sqlite:///" URLs are auto-rewritten to use aiosqlite.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from infrastructure.metadata_db.models import Base
from shared.logging.structured_logging import get_logger
from infrastructure.metadata_db.schema_repair import (
    repair_go_engine_metadata,
    repair_replication_stream_metadata,
)

_DEFAULT_DB_URL = "sqlite+aiosqlite:///migration_platform.db"
logger = get_logger(__name__)


def _resolve_url() -> str:
    url = os.environ.get("METADATA_DB_URL", _DEFAULT_DB_URL)
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif url.startswith("sqlite:///") and not url.startswith("sqlite+aiosqlite:///"):
        url = url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    return url


# Module-level singletons — created once, reused for the process lifetime.
_engine = create_async_engine(
    _resolve_url(),
    echo=False,
    pool_pre_ping=True,
    # SQLite requires check_same_thread=False for async use.
    connect_args={"check_same_thread": False} if _resolve_url().startswith("sqlite") else {},
)

AsyncSessionFactory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    _engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


def _alembic_cfg():
    from alembic.config import Config

    root = Path(__file__).resolve().parents[2]
    return Config(str(root / "alembic.ini"))


def _alembic_stamp(revision: str) -> None:
    from alembic import command

    command.stamp(_alembic_cfg(), revision)


def _alembic_upgrade(revision: str = "head") -> None:
    from alembic import command

    command.upgrade(_alembic_cfg(), revision)


async def _bootstrap_legacy_alembic() -> None:
    """Upgrade pre-2026 databases that still use generic ``id`` primary keys."""
    async with _engine.connect() as conn:
        tables = await conn.run_sync(
            lambda sync_conn: set(inspect(sync_conn).get_table_names())
        )
        if "project_connections" not in tables:
            return
        cols = await conn.run_sync(
            lambda sync_conn: {c["name"] for c in inspect(sync_conn).get_columns("project_connections")}
        )
        if "project_connection_id" in cols or "id" not in cols:
            return

        has_project_id = "project_id" in cols
        has_programs = "migration_programs" in tables

        if has_programs and not has_project_id:
            await asyncio.to_thread(_alembic_stamp, "005")
            await asyncio.to_thread(_alembic_upgrade, "006")
            await asyncio.to_thread(_alembic_stamp, "007")
        elif has_project_id and has_programs:
            await asyncio.to_thread(_alembic_stamp, "007")
        elif not has_project_id:
            await asyncio.to_thread(_alembic_stamp, "005")
            await asyncio.to_thread(_alembic_upgrade, "head")
        else:
            await asyncio.to_thread(_alembic_stamp, "head")


async def _uses_legacy_id_columns() -> bool:
    """True when project_connections still has an ``id`` PK from old Alembic revisions."""
    async with _engine.connect() as conn:
        tables = await conn.run_sync(
            lambda sync_conn: set(inspect(sync_conn).get_table_names())
        )
        if "project_connections" not in tables:
            return False
        cols = await conn.run_sync(
            lambda sync_conn: {c["name"] for c in inspect(sync_conn).get_columns("project_connections")}
        )
        return "id" in cols and "project_connection_id" not in cols


def _cleanup_stale_sqlite_if_postgres() -> None:
    """Drop legacy SQLite file when PostgreSQL metadata store is configured."""
    url = os.environ.get("METADATA_DB_URL", "")
    if "postgresql" not in url:
        return
    stale = Path(__file__).resolve().parents[2] / "migration_platform.db"
    if stale.exists():
        stale.unlink()


async def _alembic_version_exists() -> bool:
    async with _engine.connect() as conn:
        tables = await conn.run_sync(
            lambda sync_conn: set(inspect(sync_conn).get_table_names())
        )
        return "alembic_version" in tables


def _column_names(sync_conn, table: str) -> set[str]:
    if table not in inspect(sync_conn).get_table_names():
        return set()
    return {c["name"] for c in inspect(sync_conn).get_columns(table)}


async def _schema_is_orm_compatible() -> bool:
    """False when legacy Alembic tables (``id`` PKs) block ORM ``create_all``."""
    async with _engine.connect() as conn:
        tables = await conn.run_sync(lambda sync_conn: set(inspect(sync_conn).get_table_names()))
        if not tables:
            return True
        job_cols = await conn.run_sync(lambda sync_conn: _column_names(sync_conn, "migration_jobs"))
        if job_cols and "migration_job_id" not in job_cols:
            return False
        conn_cols = await conn.run_sync(
            lambda sync_conn: _column_names(sync_conn, "project_connections")
        )
        if conn_cols and "project_connection_id" not in conn_cols and "id" in conn_cols:
            return False
    return True


async def _drop_all_metadata_tables(conn) -> None:
    """Drop every metadata table, including legacy Alembic layouts not in the ORM.

    ``Base.metadata.drop_all`` fails when ``project_connections`` and
    ``project_projects`` reference each other. PostgreSQL dev DBs use schema reset;
    SQLite disables FK checks for the drop pass.
    """
    url = _resolve_url()
    if url.startswith("postgresql"):

        def _reset_public_schema(sync_conn) -> None:
            sync_conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            sync_conn.execute(text("CREATE SCHEMA public"))
            sync_conn.execute(text("GRANT ALL ON SCHEMA public TO CURRENT_USER"))
            sync_conn.execute(text("GRANT ALL ON SCHEMA public TO public"))

        await conn.run_sync(_reset_public_schema)
        return

    def _drop_sqlite_tables(sync_conn) -> None:
        sync_conn.execute(text("PRAGMA foreign_keys = OFF"))
        existing = set(inspect(sync_conn).get_table_names())
        for name in existing:
            if name == "sqlite_sequence":
                continue
            sync_conn.execute(text(f'DROP TABLE IF EXISTS "{name}"'))
        sync_conn.execute(text("PRAGMA foreign_keys = ON"))

    await conn.run_sync(_drop_sqlite_tables)


async def _reset_incompatible_metadata_schema() -> None:
    """Drop legacy/partial schema so ``create_all`` can build the current ORM tables."""
    logger.warning(
        "metadata_schema_incompatible",
        action="drop_and_recreate",
        hint="Caused by an old Alembic layout (e.g. migration_jobs.id). Dev data will be lost.",
    )
    async with _engine.begin() as conn:
        await _drop_all_metadata_tables(conn)


async def init_db() -> None:
    """Ensure metadata tables exist and schema matches the current ORM models.

    Fresh installs: SQLAlchemy ``create_all`` + Alembic stamp (no incremental run).
    Existing DBs: run ``alembic upgrade head`` so new revisions (e.g. 008/009) apply
    even when a prior startup only stamped head without executing migrations.
    Legacy DBs with old ``id`` columns: run targeted Alembic upgrades first.
    """
    _cleanup_stale_sqlite_if_postgres()
    if not await _schema_is_orm_compatible():
        await _reset_incompatible_metadata_schema()
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    if await _uses_legacy_id_columns():
        await _bootstrap_legacy_alembic()
    if await _alembic_version_exists():
        await asyncio.to_thread(_alembic_upgrade, "head")
    else:
        await asyncio.to_thread(_alembic_stamp, "head")
    async with _engine.begin() as conn:
        await conn.run_sync(repair_go_engine_metadata)
        await conn.run_sync(repair_replication_stream_metadata)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a single-request DB session."""
    async with AsyncSessionFactory() as session:
        yield session
