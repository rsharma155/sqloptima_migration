"""HTTP-level security tests for auth and RBAC.

Uses httpx AsyncClient with ASGI transport — no real server needed.
Each test class gets a fresh in-memory DB via a monkeypatched session factory.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import os

# Must be set before importing anything that touches the auth middleware.
os.environ["MIGRATION_JWT_SECRET"] = "test-jwt-secret-for-auth-endpoint-tests"
os.environ["MIGRATION_MASTER_KEY"] = "test-master-key-for-auth-endpoint-tests"
os.environ["MIGRATION_ADMIN_PASSWORD"] = "admin-test-password"
os.environ["METADATA_DB_URL"] = "sqlite+aiosqlite:///:memory:"

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from application.auth_service import AuthService
from apps.api.middleware.auth import create_access_token, create_refresh_token
from infrastructure.metadata_db.models import Base
from infrastructure.metadata_db.session import AsyncSessionFactory


# ---------------------------------------------------------------------------
# Shared fixtures: fresh in-memory DB + patched session factory per test
# ---------------------------------------------------------------------------

@pytest.fixture
async def db_factory():
    """Create a fresh in-memory DB and return its session factory.

    StaticPool forces all connections to reuse the same underlying SQLite
    connection so the in-memory database is shared across sessions.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    yield factory
    await engine.dispose()


@pytest.fixture
def patch_session(db_factory, monkeypatch):
    """Point every module-level AsyncSessionFactory binding to the test DB.

    Each module that does `from infrastructure.metadata_db.session import AsyncSessionFactory`
    holds its own local binding.  We must patch each one individually.
    """
    import infrastructure.metadata_db.session as session_mod
    import apps.api.routers.auth_router as auth_router_mod
    import application.migration_service as migration_svc_mod
    import apps.api.connection_store as conn_store_mod

    for mod in (session_mod, auth_router_mod, migration_svc_mod, conn_store_mod):
        monkeypatch.setattr(mod, "AsyncSessionFactory", db_factory)
    return db_factory


@pytest.fixture
async def seeded_db(patch_session):
    """Seed the test DB with admin, operator, and viewer users."""
    async with patch_session() as sess:
        svc = AuthService(sess)
        await svc.create_user("admin", "admin@test.com", "admin-test-password", "admin")
        await svc.create_user("operator", "op@test.com", "op-password", "operator")
        await svc.create_user("viewer", "viewer@test.com", "view-password", "viewer")
    return patch_session


@pytest.fixture
async def client(seeded_db):
    """HTTP client wired to the FastAPI app with a seeded test DB."""
    from apps.api.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _login(client: AsyncClient, username: str, password: str) -> dict:
    resp = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _admin_token(client: AsyncClient) -> str:
    data = await _login(client, "admin", "admin-test-password")
    return data["access_token"]


async def _operator_token(client: AsyncClient) -> str:
    data = await _login(client, "operator", "op-password")
    return data["access_token"]


async def _viewer_token(client: AsyncClient) -> str:
    data = await _login(client, "viewer", "view-password")
    return data["access_token"]


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

class TestLogin:
    async def test_valid_login_returns_token_pair(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin-test-password"})
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert "refresh_token" in body
        assert body["token_type"] == "bearer"

    async def test_wrong_password_returns_401(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
        assert resp.status_code == 401

    async def test_unknown_user_returns_401(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/login", json={"username": "ghost", "password": "anything"})
        assert resp.status_code == 401

    async def test_login_token_contains_role_claim(self, client: AsyncClient):
        import jwt as pyjwt
        data = await _login(client, "operator", "op-password")
        payload = pyjwt.decode(
            data["access_token"],
            options={"verify_signature": False},
        )
        assert payload["role"] == "operator"
        assert payload["sub"] != ""

    async def test_missing_credentials_returns_422(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/login", json={"username": "admin"})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Token refresh
# ---------------------------------------------------------------------------

class TestTokenRefresh:
    async def test_valid_refresh_returns_new_token_pair(self, client: AsyncClient):
        data = await _login(client, "admin", "admin-test-password")
        resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": data["refresh_token"]})
        assert resp.status_code == 200
        new_data = resp.json()
        assert "access_token" in new_data
        assert "refresh_token" in new_data
        # Tokens are rotated — they must differ from the originals.
        assert new_data["access_token"] != data["access_token"]
        assert new_data["refresh_token"] != data["refresh_token"]

    async def test_used_refresh_token_is_rejected(self, client: AsyncClient):
        data = await _login(client, "admin", "admin-test-password")
        refresh = data["refresh_token"]
        await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
        # Second use of the same refresh token must fail.
        resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
        assert resp.status_code == 401

    async def test_invalid_refresh_token_returns_401(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": "garbage.token.value"})
        assert resp.status_code == 401

    async def test_access_token_rejected_as_refresh(self, client: AsyncClient):
        data = await _login(client, "admin", "admin-test-password")
        resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": data["access_token"]})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Unauthenticated access
# ---------------------------------------------------------------------------

class TestUnauthenticated:
    async def test_missing_auth_header_returns_401(self, client: AsyncClient):
        resp = await client.get("/api/v1/migrations")
        assert resp.status_code == 401

    async def test_malformed_bearer_returns_401(self, client: AsyncClient):
        resp = await client.get("/api/v1/migrations", headers={"Authorization": "Token abc"})
        assert resp.status_code == 401

    async def test_expired_token_returns_401(self, client: AsyncClient):
        from datetime import UTC, datetime, timedelta
        import jwt as pyjwt
        expired_payload = {
            "sub": "admin",
            "role": "admin",
            "typ": "access",
            "iat": datetime.now(UTC) - timedelta(hours=10),
            "exp": datetime.now(UTC) - timedelta(hours=2),
        }
        expired_token = pyjwt.encode(expired_payload, "test-jwt-secret-for-auth-endpoint-tests", algorithm="HS256")
        resp = await client.get("/api/v1/migrations", headers={"Authorization": f"Bearer {expired_token}"})
        assert resp.status_code == 401

    async def test_tampered_token_returns_401(self, client: AsyncClient):
        data = await _login(client, "admin", "admin-test-password")
        parts = data["access_token"].split(".")
        tampered = parts[0] + "." + parts[1] + ".BAD_SIGNATURE"
        resp = await client.get("/api/v1/migrations", headers={"Authorization": f"Bearer {tampered}"})
        assert resp.status_code == 401

    async def test_health_is_public(self, client: AsyncClient):
        resp = await client.get("/health")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Role-based access control
# ---------------------------------------------------------------------------

class TestRBAC:
    async def test_viewer_can_read_migrations(self, client: AsyncClient):
        token = await _viewer_token(client)
        resp = await client.get("/api/v1/migrations", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    async def test_viewer_cannot_start_migration(self, client: AsyncClient):
        token = await _viewer_token(client)
        resp = await client.post(
            "/api/v1/migrations",
            json={
                "source_connection_id": "00000000-0000-0000-0000-000000000001",
                "target_connection_id": "00000000-0000-0000-0000-000000000002",
                "tables": ["users"],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    async def test_operator_can_start_migration(self, client: AsyncClient):
        token = await _operator_token(client)
        resp = await client.post(
            "/api/v1/migrations",
            json={
                "source_connection_id": "00000000-0000-0000-0000-000000000001",
                "target_connection_id": "00000000-0000-0000-0000-000000000002",
                "tables": ["users"],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        # 404 is fine — no connection exists. What matters is it passed the role check (not 403).
        assert resp.status_code != 403

    async def test_viewer_cannot_delete_connection(self, client: AsyncClient):
        token = await _viewer_token(client)
        resp = await client.delete(
            "/api/v1/connections/some-id",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    async def test_operator_can_delete_connection(self, client: AsyncClient):
        token = await _operator_token(client)
        resp = await client.delete(
            "/api/v1/connections/some-id",
            headers={"Authorization": f"Bearer {token}"},
        )
        # 404 is fine — connection doesn't exist, but role check passed.
        assert resp.status_code == 404

    async def test_admin_can_delete_connection(self, client: AsyncClient):
        token = await _admin_token(client)
        resp = await client.delete(
            "/api/v1/connections/nonexistent-id",
            headers={"Authorization": f"Bearer {token}"},
        )
        # 404 is fine — connection doesn't exist, but role check passed.
        assert resp.status_code == 404

    async def test_viewer_cannot_list_users(self, client: AsyncClient):
        token = await _viewer_token(client)
        resp = await client.get("/api/v1/users", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403

    async def test_operator_cannot_list_users(self, client: AsyncClient):
        token = await _operator_token(client)
        resp = await client.get("/api/v1/users", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403

    async def test_admin_can_list_users(self, client: AsyncClient):
        token = await _admin_token(client)
        resp = await client.get("/api/v1/users", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        users = resp.json()
        assert len(users) == 3

    async def test_admin_can_create_user(self, client: AsyncClient):
        token = await _admin_token(client)
        resp = await client.post(
            "/api/v1/users",
            json={"username": "newuser", "email": "new@test.com", "password": "pw", "role": "viewer"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        assert resp.json()["username"] == "newuser"

    async def test_admin_cannot_delete_self(self, client: AsyncClient):
        token = await _admin_token(client)
        # Get admin's user ID first.
        users_resp = await client.get("/api/v1/users", headers={"Authorization": f"Bearer {token}"})
        admin_id = next(u["id"] for u in users_resp.json() if u["username"] == "admin")
        resp = await client.delete(f"/api/v1/users/{admin_id}", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 400

    async def test_admin_can_delete_other_user(self, client: AsyncClient):
        token = await _admin_token(client)
        headers = {"Authorization": f"Bearer {token}"}
        create = await client.post(
            "/api/v1/users",
            json={"username": "doomed", "email": "doomed@test.com", "password": "pw", "role": "viewer"},
            headers=headers,
        )
        assert create.status_code == 201
        doomed_id = create.json()["id"]
        delete = await client.delete(f"/api/v1/users/{doomed_id}", headers=headers)
        assert delete.status_code == 200
        assert delete.json() == {"deleted": True}
        users = await client.get("/api/v1/users", headers=headers)
        assert all(u["id"] != doomed_id for u in users.json())
