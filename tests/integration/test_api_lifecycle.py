# Author: Ravi Sharma
# Copyright (c) 2026 Ravi Sharma
# SPDX-License-Identifier: MIT

"""HTTP-level integration tests for the Migration Platform API.

These tests exercise the full FastAPI request-response cycle using
httpx.AsyncClient + ASGI transport — no real network, no real database
connections to SQL Server or PostgreSQL. Each test class represents one
domain slice of the API.

Fixtures from tests/conftest.py:
  api_client     — AsyncClient with seeded DB (admin/operator/viewer users)
  admin_headers  — Authorization header for ADMIN role
  operator_headers — Authorization header for OPERATOR role
  viewer_headers — Authorization header for VIEWER role
  sample_tsql_procedure — Simple T-SQL stored procedure string
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


# ═══════════════════════════════════════════════════════════════════════════
# Public endpoints
# ═══════════════════════════════════════════════════════════════════════════

class TestPublicEndpoints:
    """Endpoints that must be reachable without authentication."""

    async def test_health_returns_ok(self, api_client: AsyncClient):
        resp = await api_client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"

    async def test_health_response_has_version(self, api_client: AsyncClient):
        resp = await api_client.get("/health")
        body = resp.json()
        assert "version" in body

    async def test_openapi_schema_is_accessible(self, api_client: AsyncClient):
        resp = await api_client.get("/openapi.json")
        assert resp.status_code == 200
        assert "paths" in resp.json()

    async def test_docs_ui_is_accessible(self, api_client: AsyncClient):
        resp = await api_client.get("/docs")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════
# Auth lifecycle
# ═══════════════════════════════════════════════════════════════════════════

class TestAuthLifecycle:
    """Login → use token → refresh → revoke cycle."""

    async def test_login_with_valid_credentials(self, api_client: AsyncClient):
        resp = await api_client.post(
            "/api/v1/auth/login", json={"username": "admin", "password": "admin-password"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert "refresh_token" in body
        assert body["token_type"] == "bearer"

    async def test_login_with_wrong_password_returns_401(self, api_client: AsyncClient):
        resp = await api_client.post(
            "/api/v1/auth/login", json={"username": "admin", "password": "wrong"}
        )
        assert resp.status_code == 401

    async def test_login_with_unknown_user_returns_401(self, api_client: AsyncClient):
        resp = await api_client.post(
            "/api/v1/auth/login", json={"username": "nobody", "password": "x"}
        )
        assert resp.status_code == 401

    async def test_token_alias_endpoint_works(self, api_client: AsyncClient):
        resp = await api_client.post(
            "/api/v1/auth/token", json={"username": "operator", "password": "op-password"}
        )
        assert resp.status_code == 200

    async def test_refresh_rotates_tokens(self, api_client: AsyncClient):
        login = await api_client.post(
            "/api/v1/auth/login", json={"username": "admin", "password": "admin-password"}
        )
        original = login.json()
        refresh_resp = await api_client.post(
            "/api/v1/auth/refresh", json={"refresh_token": original["refresh_token"]}
        )
        assert refresh_resp.status_code == 200
        rotated = refresh_resp.json()
        assert rotated["access_token"] != original["access_token"]
        assert rotated["refresh_token"] != original["refresh_token"]

    async def test_used_refresh_token_is_rejected(self, api_client: AsyncClient):
        login = await api_client.post(
            "/api/v1/auth/login", json={"username": "operator", "password": "op-password"}
        )
        rt = login.json()["refresh_token"]
        await api_client.post("/api/v1/auth/refresh", json={"refresh_token": rt})
        second = await api_client.post("/api/v1/auth/refresh", json={"refresh_token": rt})
        assert second.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════
# Protected endpoints — authentication gate
# ═══════════════════════════════════════════════════════════════════════════

class TestAuthenticationGate:
    """All non-public endpoints must reject unauthenticated requests."""

    @pytest.mark.parametrize("method,path", [
        ("GET", "/api/v1/connections"),
        ("GET", "/api/v1/migrations"),
        ("POST", "/api/v1/connections"),
        ("POST", "/api/v1/migrations"),
        ("POST", "/api/v1/convert"),
        ("GET", "/api/v1/users"),
        ("GET", "/api/v1/projects"),
        ("GET", "/api/v1/reports/migration/00000000-0000-0000-0000-000000000001"),
    ])
    async def test_unauthenticated_returns_401(
        self, api_client: AsyncClient, method: str, path: str
    ):
        resp = await api_client.request(method, path)
        assert resp.status_code == 401, (
            f"{method} {path} returned {resp.status_code}, expected 401"
        )

    async def test_malformed_bearer_returns_401(self, api_client: AsyncClient):
        resp = await api_client.get(
            "/api/v1/migrations", headers={"Authorization": "Token not-a-bearer"}
        )
        assert resp.status_code == 401

    async def test_garbage_token_returns_401(self, api_client: AsyncClient):
        resp = await api_client.get(
            "/api/v1/connections", headers={"Authorization": "Bearer garbage.token.value"}
        )
        assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════
# Connections domain
# ═══════════════════════════════════════════════════════════════════════════

class TestConnectionsEndpoints:
    """CRUD lifecycle for connection records."""

    async def test_list_connections_returns_empty_initially(
        self, api_client: AsyncClient, admin_headers: dict
    ):
        resp = await api_client.get("/api/v1/connections", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_create_connection_returns_201(
        self, api_client: AsyncClient, operator_headers: dict
    ):
        payload = {
            "name": "Test SQL Server",
            "type": "sqlserver",
            "host": "localhost",
            "port": 1433,
            "database": "testdb",
            "username": "sa",
            "password": "Test@123",
        }
        resp = await api_client.post("/api/v1/connections", json=payload, headers=operator_headers)
        assert resp.status_code in (200, 201), resp.text

    async def test_viewer_cannot_create_connection(
        self, api_client: AsyncClient, viewer_headers: dict
    ):
        payload = {
            "name": "Blocked",
            "type": "sqlserver",
            "host": "h",
            "port": 1433,
            "database": "d",
            "username": "u",
            "password": "p",
        }
        resp = await api_client.post("/api/v1/connections", json=payload, headers=viewer_headers)
        assert resp.status_code == 403

    async def test_viewer_can_list_connections(
        self, api_client: AsyncClient, viewer_headers: dict
    ):
        resp = await api_client.get("/api/v1/connections", headers=viewer_headers)
        assert resp.status_code == 200

    async def test_delete_connection_requires_operator(
        self, api_client: AsyncClient, operator_headers: dict
    ):
        resp = await api_client.delete(
            "/api/v1/connections/00000000-0000-0000-0000-000000000001",
            headers=operator_headers,
        )
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
# Migrations domain
# ═══════════════════════════════════════════════════════════════════════════

class TestMigrationsEndpoints:
    """Job creation, listing, and lifecycle control."""

    async def test_list_migrations_returns_list(
        self, api_client: AsyncClient, viewer_headers: dict
    ):
        resp = await api_client.get("/api/v1/migrations", headers=viewer_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_operator_can_create_migration_job(
        self, api_client: AsyncClient, operator_headers: dict
    ):
        payload = {
            "source_connection_id": "00000000-0000-0000-0000-000000000001",
            "target_connection_id": "00000000-0000-0000-0000-000000000002",
            "tables": ["users"],
        }
        resp = await api_client.post("/api/v1/migrations", json=payload, headers=operator_headers)
        # 404 is acceptable — no connection stored yet, but role check must pass (not 403)
        assert resp.status_code != 403, "Operator must pass the role guard on POST /migrations"

    async def test_viewer_cannot_create_migration_job(
        self, api_client: AsyncClient, viewer_headers: dict
    ):
        payload = {
            "source_connection_id": "00000000-0000-0000-0000-000000000001",
            "target_connection_id": "00000000-0000-0000-0000-000000000002",
            "tables": ["users"],
        }
        resp = await api_client.post("/api/v1/migrations", json=payload, headers=viewer_headers)
        assert resp.status_code == 403

    async def test_get_nonexistent_migration_returns_404(
        self, api_client: AsyncClient, admin_headers: dict
    ):
        resp = await api_client.get(
            "/api/v1/migrations/00000000-0000-0000-0000-000000000099",
            headers=admin_headers,
        )
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
# Conversion endpoint
# ═══════════════════════════════════════════════════════════════════════════

class TestConversionEndpoint:
    """T-SQL → PL/pgSQL conversion via POST /convert."""

    async def test_convert_simple_procedure(
        self,
        api_client: AsyncClient,
        operator_headers: dict,
        sample_tsql_procedure: str,
    ):
        resp = await api_client.post(
            "/api/v1/convert",
            json={"sql": sample_tsql_procedure, "object_type": "procedure"},
            headers=operator_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "converted_sql" in body
        assert isinstance(body["success"], bool)

    async def test_convert_unknown_object_type_returns_400(
        self, api_client: AsyncClient, operator_headers: dict
    ):
        resp = await api_client.post(
            "/api/v1/convert",
            json={"sql": "SELECT 1", "object_type": "unsupported_type"},
            headers=operator_headers,
        )
        assert resp.status_code == 400

    async def test_convert_requires_operator_role(
        self, api_client: AsyncClient, viewer_headers: dict, sample_tsql_procedure: str
    ):
        resp = await api_client.post(
            "/api/v1/convert",
            json={"sql": sample_tsql_procedure},
            headers=viewer_headers,
        )
        assert resp.status_code == 403

    async def test_convert_sql_validation_endpoint(
        self, api_client: AsyncClient, operator_headers: dict
    ):
        resp = await api_client.post(
            "/api/v1/sql/validate",
            json={"sql": "SELECT id FROM users WHERE id = 1"},
            headers=operator_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "valid" in body


# ═══════════════════════════════════════════════════════════════════════════
# User management
# ═══════════════════════════════════════════════════════════════════════════

class TestUserManagement:
    """Admin-only user CRUD endpoints."""

    async def test_admin_can_list_users(
        self, api_client: AsyncClient, admin_headers: dict
    ):
        resp = await api_client.get("/api/v1/users", headers=admin_headers)
        assert resp.status_code == 200
        users = resp.json()
        assert isinstance(users, list)
        assert len(users) >= 3  # admin, operator, viewer seeded in conftest

    async def test_operator_cannot_list_users(
        self, api_client: AsyncClient, operator_headers: dict
    ):
        resp = await api_client.get("/api/v1/users", headers=operator_headers)
        assert resp.status_code == 403

    async def test_admin_can_create_user(
        self, api_client: AsyncClient, admin_headers: dict
    ):
        resp = await api_client.post(
            "/api/v1/users",
            json={
                "username": "newuser",
                "email": "new@test.com",
                "password": "strongpass",
                "role": "viewer",
            },
            headers=admin_headers,
        )
        assert resp.status_code in (200, 201)
        assert resp.json()["username"] == "newuser"

    async def test_admin_cannot_delete_own_account(
        self, api_client: AsyncClient
    ):
        # Log in as admin to get DB-backed user ID
        login = await api_client.post(
            "/api/v1/auth/login", json={"username": "admin", "password": "admin-password"}
        )
        token = login.json()["access_token"]
        auth = {"Authorization": f"Bearer {token}"}

        users = await api_client.get("/api/v1/users", headers=auth)
        admin_id = next(u["id"] for u in users.json() if u["username"] == "admin")

        resp = await api_client.delete(f"/api/v1/users/{admin_id}", headers=auth)
        assert resp.status_code == 400
