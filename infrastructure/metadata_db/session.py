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

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from infrastructure.metadata_db.models import Base
from infrastructure.metadata_db.schema_repair import (
    repair_go_engine_metadata,
    repair_replication_stream_metadata,
)

_DEFAULT_DB_URL = "sqlite+aiosqlite:///migration_platform.db"


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


async def init_db() -> None:
    """Ensure metadata tables exist and schema matches the current ORM models.

    Fresh installs: SQLAlchemy ``create_all`` + Alembic stamp (no incremental run).
    Existing DBs: run ``alembic upgrade head`` so new revisions (e.g. 008/009) apply
    even when a prior startup only stamped head without executing migrations.
    Legacy DBs with old ``id`` columns: run targeted Alembic upgrades first.
    """
    _cleanup_stale_sqlite_if_postgres()
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
