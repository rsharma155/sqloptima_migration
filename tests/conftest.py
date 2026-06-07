# Author: Ravi Sharma
# Copyright (c) 2026 Ravi Sharma
# SPDX-License-Identifier: MIT

"""Root pytest conftest — shared fixtures available to every test module.

Provides:
  - In-memory SQLite DB engine + session factory (per-test isolation).
  - Session-factory monkeypatching so routers and services hit the test DB.
  - Seeded admin / operator / viewer users.
  - httpx AsyncClient wired to the FastAPI app.
  - JWT auth-header helpers for each role.
  - Sample T-SQL strings for converter/parser tests.

All database fixtures use StaticPool so a single in-memory connection is
shared across sessions in the same test — required for SQLite in-memory mode.
"""

from __future__ import annotations

import os

# ── Env vars must be set before any app module is imported ──────────────────
os.environ.setdefault("MIGRATION_JWT_SECRET", "conftest-jwt-secret-at-least-32-chars-long!")
os.environ.setdefault("MIGRATION_MASTER_KEY", "conftest-master-key-placeholder-value-here")
os.environ.setdefault("MIGRATION_ADMIN_PASSWORD", "conftest-admin-password")
os.environ.setdefault("METADATA_DB_URL", "sqlite+aiosqlite:///:memory:")

# ── Standard imports ─────────────────────────────────────────────────────────
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from application.auth_service import AuthService
from apps.api.middleware.auth import UserRole, create_access_token
from infrastructure.metadata_db.models import Base

# ═══════════════════════════════════════════════════════════════════════════
# Database infrastructure
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
async def test_db_engine():
    """Fresh in-memory SQLite engine with all tables created.

    StaticPool forces every async connection to reuse the same underlying
    SQLite connection, which is required for in-memory databases.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def test_session_factory(test_db_engine):
    """Async session factory bound to the test engine."""
    return async_sessionmaker(
        test_db_engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )


@pytest.fixture
def patch_db_session(test_session_factory, monkeypatch):
    """Redirect every module that holds an AsyncSessionFactory binding to the
    test DB.  Each module that does:
        from infrastructure.metadata_db.session import AsyncSessionFactory
    holds its own reference, so each must be patched individually.
    """
    import apps.api.routers.auth_router as auth_router_mod
    import infrastructure.metadata_db.session as session_mod

    targets = [session_mod, auth_router_mod]

    # Patch additional routers that may exist
    optional_routers = [
        "apps.api.routers.connections_router",
        "apps.api.routers.migrations_router",
        "apps.api.routers.validation_router",
        "apps.api.routers.projects_router",
        "apps.api.routers.reports_router",
        "apps.api.routers.admin_router",
        "apps.api.connection_store",
        "application.migration_service",
        "application.replication_service",
        "application.auth_service",
    ]
    import importlib
    for mod_path in optional_routers:
        try:
            mod = importlib.import_module(mod_path)
            if hasattr(mod, "AsyncSessionFactory"):
                targets.append(mod)
        except ImportError:
            pass

    for mod in targets:
        monkeypatch.setattr(mod, "AsyncSessionFactory", test_session_factory, raising=False)

    return test_session_factory


@pytest.fixture
async def seeded_db(patch_db_session):
    """Seed test DB with admin / operator / viewer users and return the
    patched session factory.
    """
    async with patch_db_session() as sess:
        svc = AuthService(sess)
        await svc.create_user("admin", "admin@test.com", "admin-password", "admin")
        await svc.create_user("operator", "op@test.com", "op-password", "operator")
        await svc.create_user("viewer", "viewer@test.com", "view-password", "viewer")
    return patch_db_session


# ═══════════════════════════════════════════════════════════════════════════
# HTTP client
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
async def api_client(seeded_db):
    """httpx AsyncClient wired to the FastAPI app with a seeded test DB.

    Use this in integration and security tests that need a running API.
    The seeded_db fixture ensures admin/operator/viewer users exist before
    the first request is made.
    """
    from apps.api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
async def bare_api_client():
    """httpx AsyncClient with no DB seeding — for tests that need an empty DB
    or that test only public endpoints (e.g. /health).
    """
    from apps.api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


# ═══════════════════════════════════════════════════════════════════════════
# Auth header helpers
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def admin_headers() -> dict[str, str]:
    """Authorization header carrying a valid ADMIN JWT (no DB call needed)."""
    token = create_access_token("admin-test-id", UserRole.ADMIN.value)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def operator_headers() -> dict[str, str]:
    """Authorization header carrying a valid OPERATOR JWT."""
    token = create_access_token("operator-test-id", UserRole.OPERATOR.value)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def viewer_headers() -> dict[str, str]:
    """Authorization header carrying a valid VIEWER JWT."""
    token = create_access_token("viewer-test-id", UserRole.VIEWER.value)
    return {"Authorization": f"Bearer {token}"}


# ═══════════════════════════════════════════════════════════════════════════
# Sample T-SQL strings
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def sample_tsql_procedure() -> str:
    """Simple T-SQL stored procedure for converter / parser tests."""
    return """\
CREATE PROCEDURE dbo.usp_GetUserById
    @UserId INT
AS
BEGIN
    SET NOCOUNT ON;
    SELECT id, name, email
    FROM dbo.Users WITH (NOLOCK)
    WHERE id = @UserId;
END
"""


@pytest.fixture
def sample_tsql_function() -> str:
    """Simple T-SQL scalar function."""
    return """\
CREATE FUNCTION dbo.fn_FullName(@First NVARCHAR(50), @Last NVARCHAR(50))
RETURNS NVARCHAR(101)
AS
BEGIN
    RETURN @First + ' ' + @Last;
END
"""


@pytest.fixture
def sample_tsql_trigger() -> str:
    """Simple T-SQL AFTER INSERT trigger."""
    return """\
CREATE TRIGGER dbo.trg_AuditInsert
ON dbo.Orders
AFTER INSERT
AS
BEGIN
    INSERT INTO dbo.AuditLog (action, table_name, created_at)
    VALUES ('INSERT', 'Orders', GETDATE());
END
"""


@pytest.fixture
def sample_tsql_merge() -> str:
    """T-SQL MERGE statement (converted to INSERT … ON CONFLICT)."""
    return """\
MERGE INTO dbo.Products AS target
USING (SELECT 1 AS product_id, 'Widget' AS name) AS source
ON target.product_id = source.product_id
WHEN MATCHED THEN
    UPDATE SET name = source.name
WHEN NOT MATCHED THEN
    INSERT (product_id, name) VALUES (source.product_id, source.name);
"""
