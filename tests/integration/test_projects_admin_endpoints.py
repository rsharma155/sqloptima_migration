# Author: Ravi Sharma
# Copyright (c) 2026 Ravi Sharma
# SPDX-License-Identifier: MIT

"""HTTP-level integration tests for the endpoints added in the post-Phase-14 work.

Covers the surface NOT already exercised by ``test_api_lifecycle.py``:
  - Projects router  (CRUD, RBAC, uniqueness, verbatim storage of unsafe names)
  - Admin router     (retention dry-run, ODBC check, diagnostics; ADMIN-only)
  - Schema mapping   (``/convert`` with a ``schema_mapping`` body)

Shared fixtures (``api_client``, ``admin_headers``, ``operator_headers``,
``viewer_headers``) come from tests/conftest.py.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

# ---------------------------------------------------------------------------
# Projects router
# ---------------------------------------------------------------------------


class TestProjectsCrud:
    @pytest.mark.asyncio
    async def test_list_projects_empty_initially(
        self, api_client: AsyncClient, viewer_headers: dict
    ) -> None:
        resp = await api_client.get("/api/v1/projects", headers=viewer_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_operator_can_create_project(
        self, api_client: AsyncClient, operator_headers: dict
    ) -> None:
        resp = await api_client.post(
            "/api/v1/projects",
            json={"name": "Acme Migration", "description": "Test project"},
            headers=operator_headers,
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "Acme Migration"
        assert "id" in body

    @pytest.mark.asyncio
    async def test_duplicate_name_returns_409(
        self, api_client: AsyncClient, operator_headers: dict
    ) -> None:
        await api_client.post("/api/v1/projects", json={"name": "Dup"}, headers=operator_headers)
        resp = await api_client.post(
            "/api/v1/projects", json={"name": "Dup"}, headers=operator_headers
        )
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_viewer_cannot_create_project(
        self, api_client: AsyncClient, viewer_headers: dict
    ) -> None:
        resp = await api_client.post(
            "/api/v1/projects", json={"name": "Forbidden"}, headers=viewer_headers
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_get_project_by_id(
        self, api_client: AsyncClient, operator_headers: dict
    ) -> None:
        created = await api_client.post(
            "/api/v1/projects", json={"name": "FindMe"}, headers=operator_headers
        )
        pid = created.json()["id"]
        resp = await api_client.get(f"/api/v1/projects/{pid}", headers=operator_headers)
        assert resp.status_code == 200
        assert resp.json()["name"] == "FindMe"

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_404(
        self, api_client: AsyncClient, viewer_headers: dict
    ) -> None:
        resp = await api_client.get(
            "/api/v1/projects/00000000-0000-0000-0000-000000000000", headers=viewer_headers
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_requires_admin(
        self,
        api_client: AsyncClient,
        operator_headers: dict,
        admin_headers: dict,
    ) -> None:
        created = await api_client.post(
            "/api/v1/projects", json={"name": "ToDelete"}, headers=operator_headers
        )
        pid = created.json()["id"]

        # Operator forbidden
        resp = await api_client.delete(f"/api/v1/projects/{pid}", headers=operator_headers)
        assert resp.status_code == 403

        # Admin allowed
        resp = await api_client.delete(f"/api/v1/projects/{pid}", headers=admin_headers)
        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_unsafe_name_stored_verbatim_not_executed(
        self, api_client: AsyncClient, operator_headers: dict
    ) -> None:
        """ORM-parameterised storage means a quote-containing name is kept literal."""
        unsafe = "Robert'); DROP TABLE project_projects; --"
        resp = await api_client.post(
            "/api/v1/projects", json={"name": unsafe}, headers=operator_headers
        )
        assert resp.status_code == 201
        assert resp.json()["name"] == unsafe
        # Table must still exist — a follow-up list must succeed
        check = await api_client.get("/api/v1/projects", headers=operator_headers)
        assert check.status_code == 200


# ---------------------------------------------------------------------------
# Admin router (retention / odbc / diagnostics)
# ---------------------------------------------------------------------------


class TestAdminRetention:
    @pytest.mark.asyncio
    async def test_dry_run_admin_only(
        self, api_client: AsyncClient, admin_headers: dict
    ) -> None:
        resp = await api_client.post(
            "/api/v1/admin/retention/run",
            json={"max_age_days": 30, "dry_run": True},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["dry_run"] is True
        assert "scanned" in body
        assert "deleted" in body

    @pytest.mark.asyncio
    async def test_operator_forbidden(
        self, api_client: AsyncClient, operator_headers: dict
    ) -> None:
        resp = await api_client.post(
            "/api/v1/admin/retention/run",
            json={"max_age_days": 30, "dry_run": True},
            headers=operator_headers,
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_invalid_max_age_returns_422(
        self, api_client: AsyncClient, admin_headers: dict
    ) -> None:
        resp = await api_client.post(
            "/api/v1/admin/retention/run",
            json={"max_age_days": 0, "dry_run": True},
            headers=admin_headers,
        )
        assert resp.status_code == 422


class TestAdminDiagnostics:
    @pytest.mark.asyncio
    async def test_odbc_check_returns_driver_list(
        self, api_client: AsyncClient, admin_headers: dict
    ) -> None:
        resp = await api_client.get("/api/v1/admin/odbc/check", headers=admin_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "available" in body
        assert "drivers" in body
        assert isinstance(body["drivers"], list)

    @pytest.mark.asyncio
    async def test_diagnostics_reports_env_and_db(
        self, api_client: AsyncClient, admin_headers: dict
    ) -> None:
        resp = await api_client.get("/api/v1/admin/diagnostics", headers=admin_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "env_vars" in body
        assert "metadata_db" in body
        assert body["metadata_db"]["connected"] is True

    @pytest.mark.asyncio
    async def test_diagnostics_forbidden_for_viewer(
        self, api_client: AsyncClient, viewer_headers: dict
    ) -> None:
        resp = await api_client.get("/api/v1/admin/diagnostics", headers=viewer_headers)
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Schema mapping via /convert
# ---------------------------------------------------------------------------


class TestConvertSchemaMapping:
    @pytest.mark.asyncio
    async def test_explicit_mapping_applied(
        self, api_client: AsyncClient, operator_headers: dict
    ) -> None:
        resp = await api_client.post(
            "/api/v1/convert",
            json={
                "sql": "SELECT * FROM dbo.orders WHERE id = 1",
                "object_type": "raw",
                "schema_mapping": {"dbo": "public"},
            },
            headers=operator_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "public.orders" in body["converted_sql"]

    @pytest.mark.asyncio
    async def test_custom_multi_schema_mapping(
        self, api_client: AsyncClient, operator_headers: dict
    ) -> None:
        resp = await api_client.post(
            "/api/v1/convert",
            json={
                "sql": "SELECT * FROM hr.employees",
                "object_type": "raw",
                "schema_mapping": {"hr": "staff"},
            },
            headers=operator_headers,
        )
        assert resp.status_code == 200
        assert "staff.employees" in resp.json()["converted_sql"]
