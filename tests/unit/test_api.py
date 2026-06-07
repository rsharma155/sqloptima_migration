"""Tests for FastAPI REST API layer.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

import os
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

# Ensure required env vars are present before importing the app.
os.environ.setdefault("MIGRATION_JWT_SECRET", "test-jwt-secret-at-least-32-characters-long")
os.environ.setdefault("MIGRATION_MASTER_KEY", "test-master-key-placeholder")
os.environ.setdefault("MIGRATION_ADMIN_PASSWORD", "admin_test_password")

from apps.api.main import app  # noqa: E402 — must come after env setup
from apps.api.middleware.auth import UserRole, create_token  # noqa: E402


def _admin_headers() -> dict[str, str]:
    """Return Authorization headers with a valid admin JWT."""
    token = create_token("admin", role=UserRole.ADMIN.value)
    return {"Authorization": f"Bearer {token}"}


def _operator_headers() -> dict[str, str]:
    """Return Authorization headers with a valid operator JWT."""
    token = create_token("operator", role=UserRole.OPERATOR.value)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestHealth:
    @pytest.mark.asyncio
    async def test_health(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"


class TestAuth:
    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401(self, client):
        """Protected endpoints must reject requests with no token."""
        resp = await client.get("/api/v1/migrations")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_viewer_forbidden_on_operator_endpoint(self, client):
        """Viewer role must be refused on OPERATOR-guarded endpoints."""
        viewer_token = create_token("viewer", role=UserRole.VIEWER.value)
        headers = {"Authorization": f"Bearer {viewer_token}"}
        req = {
            "source_connection_id": str(uuid4()),
            "target_connection_id": str(uuid4()),
            "tables": ["users"],
        }
        resp = await client.post("/api/v1/migrations", json=req, headers=headers)
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_operator_forbidden_on_admin_endpoint(self, client):
        """Operator role must be refused on ADMIN-guarded endpoints."""
        resp = await client.post(
            "/api/v1/create-database",
            json={
                "connection_id": str(uuid4()),
                "database_name": "testdb",
            },
            headers=_operator_headers(),
        )
        assert resp.status_code == 403


class TestMigrations:
    @pytest.mark.asyncio
    async def test_start_migration(self, client):
        req = {
            "source_connection_id": str(uuid4()),
            "target_connection_id": str(uuid4()),
            "tables": ["users", "orders"],
            "schema": "dbo",
            "strategy": "chunked",
            "chunk_size": 5000,
            "require_target_snapshot": False,
        }
        resp = await client.post("/api/v1/migrations", json=req, headers=_operator_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running"
        assert data["table_count"] == 2

    @pytest.mark.asyncio
    async def test_get_migration(self, client):
        req = {
            "source_connection_id": str(uuid4()),
            "target_connection_id": str(uuid4()),
            "tables": ["test"],
            "require_target_snapshot": False,
        }
        create = await client.post("/api/v1/migrations", json=req, headers=_operator_headers())
        job_id = create.json()["job_id"]

        resp = await client.get(f"/api/v1/migrations/{job_id}", headers=_operator_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == job_id

    @pytest.mark.asyncio
    async def test_get_migration_not_found(self, client):
        resp = await client.get(f"/api/v1/migrations/{uuid4()}", headers=_operator_headers())
        assert resp.status_code == 404


class TestConvert:
    @pytest.mark.asyncio
    async def test_convert_procedure(self, client):
        req = {
            "sql": "SELECT * FROM users WHERE id = @p_id;",
            "object_type": "procedure",
            "object_name": "usp_get_user",
            "schema": "dbo",
            "parameters": [{"name": "@p_id", "type": "INT"}],
        }
        resp = await client.post("/api/v1/convert", json=req, headers=_operator_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "CREATE OR REPLACE PROCEDURE" in data["converted_sql"]
        assert data["postgres_syntax_valid"] is True
        assert isinstance(data["postgres_syntax_errors"], list)
        assert isinstance(data["repairs_applied"], list)
        assert data["repair_exhausted"] is False
        assert isinstance(data["parse_unblockers_applied"], list)
        assert data["body_transform_fallback"] is False
        assert data["manual_review_required"] is False

    @pytest.mark.asyncio
    async def test_convert_function(self, client):
        req = {
            "sql": "RETURN @a + @b;",
            "object_type": "function",
            "object_name": "fn_add",
            "schema": "dbo",
            "parameters": [
                {"name": "@a", "type": "INT"},
                {"name": "@b", "type": "INT"},
            ],
        }
        resp = await client.post("/api/v1/convert", json=req, headers=_operator_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "CREATE OR REPLACE FUNCTION" in data["converted_sql"]

    @pytest.mark.asyncio
    async def test_convert_invalid_type(self, client):
        req = {
            "sql": "SELECT 1;",
            "object_type": "invalid_type",
            "object_name": "test",
            "schema": "dbo",
            "parameters": [],
        }
        resp = await client.post("/api/v1/convert", json=req, headers=_operator_headers())
        assert resp.status_code == 400


class TestValidate:
    @pytest.mark.asyncio
    async def test_validate_endpoint_unknown_connections_returns_404(self, client):
        """The validate endpoint is mounted under /api/v1. With connection IDs
        that aren't registered, it must report 404 (connection not found) before
        attempting any database work."""
        req = {
            "job_id": str(uuid4()),
            "source_connection_id": str(uuid4()),
            "target_connection_id": str(uuid4()),
            "tables": [
                {"name": "users", "schema": "dbo", "source_columns": [], "target_columns": []}
            ],
        }
        resp = await client.post("/api/v1/validate", json=req, headers=_operator_headers())
        assert resp.status_code == 404
