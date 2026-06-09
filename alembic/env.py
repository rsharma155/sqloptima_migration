"""Alembic environment for async SQLite / PostgreSQL metadata store.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

import asyncio
import os
import sys
from pathlib import Path

# Ensure the project root is on sys.path so package imports resolve.
_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


def _load_dotenv() -> None:
    """Load .env before reading METADATA_DB_URL (subprocesses do not auto-load it)."""
    env_file = _ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("\"'")
        if key:
            os.environ.setdefault(key, val)


_load_dotenv()

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from infrastructure.metadata_db.models import Base

target_metadata = Base.metadata

_raw_url = os.environ.get("METADATA_DB_URL") or os.environ.get("MIGRATION_DATABASE_METADATA_URL") or "sqlite+aiosqlite:///migration_platform.db"
# Normalise plain driver URLs to async variants.
if _raw_url.startswith("postgresql://"):
    _raw_url = _raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)
elif _raw_url.startswith("sqlite:///") and not _raw_url.startswith("sqlite+aiosqlite:///"):
    _raw_url = _raw_url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
_DB_URL = _raw_url


def run_migrations_offline() -> None:
    context.configure(
        url=_DB_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_DB_URL)
    async with engine.connect() as conn:
        await conn.run_sync(_do_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
