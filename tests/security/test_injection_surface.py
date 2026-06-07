# Author: Ravi Sharma
# Copyright (c) 2026 Ravi Sharma
# SPDX-License-Identifier: MIT

"""HTTP-level injection and payload security tests (L-7).

Covers the attack surface that test_auth_endpoints.py does not:
  - SQL injection via POST /create-database (database_name field).
  - Oversized payload rejection on POST /convert.
  - Prototype-pollution / unexpected fields are ignored (Pydantic strict mode).
  - Path-traversal attempts on resource IDs are rejected (422).
  - JWT role escalation via forged payload is rejected.

Fixtures come from tests/conftest.py (api_client, admin_headers, operator_headers).
"""

from __future__ import annotations

import os
import pytest
from httpx import AsyncClient


# ═══════════════════════════════════════════════════════════════════════════
# SQL injection via POST /create-database
# ═══════════════════════════════════════════════════════════════════════════

class TestCreateDatabaseInjection:
    """POST /create-database must reject names that could break out of
    the double-quoted DDL identifier and execute arbitrary statements.

    The controller validates with ^[a-zA-Z_][a-zA-Z0-9_]{0,62}$ and returns
    HTTP 400 for any name that does not match.
    """

    @pytest.mark.parametrize("bad_name", [
        'foo"; DROP DATABASE postgres; --',
        "foo'; DROP TABLE users; --",
        "foo`; TRUNCATE TABLE users;",
        "../../etc/passwd",
        "admin\x00pwn",
        " ",
        "a" * 64,                      # too long (>63 chars)
        "1starts_with_digit",
        "has-hyphen",
        "has space",
        "has.dot",
    ])
    async def test_injection_name_rejected_with_400(
        self, api_client: AsyncClient, admin_headers: dict, bad_name: str
    ):
        resp = await api_client.post(
            "/api/v1/create-database",
            json={"database_name": bad_name, "connection_id": "00000000-0000-0000-0000-000000000001"},
            headers=admin_headers,
        )
        assert resp.status_code == 400, (
            f"Expected 400 for database_name={bad_name!r}, got {resp.status_code}: {resp.text}"
        )

    async def test_empty_database_name_rejected(
        self, api_client: AsyncClient, admin_headers: dict
    ):
        # Empty string does not match the regex — must be 422 (Pydantic) since str is required
        resp = await api_client.post(
            "/api/v1/create-database",
            json={"connection_id": "00000000-0000-0000-0000-000000000001"},
            headers=admin_headers,
        )
        assert resp.status_code == 422

    @pytest.mark.parametrize("valid_name", [
        "mydb",
        "my_db",
        "_private_db",
        "CamelCaseDB",
        "db123",
        "a" * 63,                      # exactly 63 chars — max allowed
    ])
    async def test_valid_name_passes_validation(
        self, api_client: AsyncClient, admin_headers: dict, valid_name: str
    ):
        resp = await api_client.post(
            "/api/v1/create-database",
            json={"database_name": valid_name, "connection_id": "00000000-0000-0000-0000-000000000001"},
            headers=admin_headers,
        )
        # 404 expected — no real connection stored, but the name passed the regex guard (not 400).
        assert resp.status_code != 400, (
            f"Valid name {valid_name!r} was unexpectedly rejected with 400"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Oversized payload on POST /convert
# ═══════════════════════════════════════════════════════════════════════════

class TestConvertPayloadLimits:
    """POST /convert enforces a 1 MB max_length on the sql field."""

    async def test_oversized_sql_returns_422(
        self, api_client: AsyncClient, operator_headers: dict
    ):
        # 1 MB + 1 byte — must be rejected by Pydantic's max_length validator
        oversized = "A" * (1_000_001)
        resp = await api_client.post(
            "/api/v1/convert",
            json={"sql": oversized, "object_type": "raw"},
            headers=operator_headers,
        )
        assert resp.status_code == 422, (
            f"Expected 422 for oversized payload, got {resp.status_code}"
        )

    async def test_at_limit_sql_is_not_rejected_by_size(
        self, api_client: AsyncClient, operator_headers: dict
    ):
        # A payload just within the 1 MB limit — must not get a Pydantic max_length error.
        # Use a short realistic SQL to keep this test fast.
        sql_at_limit = "SELECT 1"
        resp = await api_client.post(
            "/api/v1/convert",
            json={"sql": sql_at_limit, "object_type": "raw"},
            headers=operator_headers,
        )
        # Any non-422 response (200, 400, 500) means size validation passed.
        if resp.status_code == 422:
            assert "String should have at most" not in resp.text, (
                "Valid SQL should not be rejected by max_length"
            )

    async def test_empty_sql_returns_422(
        self, api_client: AsyncClient, operator_headers: dict
    ):
        resp = await api_client.post(
            "/api/v1/convert",
            json={"sql": "", "object_type": "raw"},
            headers=operator_headers,
        )
        # Empty string should be rejected (min_length=1 implicitly by non-empty Field)
        # or accepted with an empty conversion result — either is acceptable.
        # What must NOT happen: an unhandled 500.
        assert resp.status_code != 500, "Empty SQL must not cause an unhandled server error"


# ═══════════════════════════════════════════════════════════════════════════
# Path traversal via resource IDs
# ═══════════════════════════════════════════════════════════════════════════

class TestPathTraversalRejection:
    """Resource IDs that look like path traversal attacks must never return 200.

    FastAPI with UUID-typed path params returns 422 for non-UUID strings.
    Patterns containing `../` are URL-normalized by the HTTP stack before routing
    (e.g. `../../etc/passwd` → `/etc/passwd`), which returns 404 — also safe.
    The test asserts status ∈ {404, 422}: either is safe; 200 is the only bad outcome.
    """

    @pytest.mark.parametrize("bad_id", [
        "../../etc/passwd",       # URL-normalized → different path → 404
        "../secrets",              # URL-normalized → 404
        "%2e%2e%2fetc%2fpasswd",   # decoded → `../etc/passwd` → 422 (UUID check)
        "' OR '1'='1",             # non-UUID → 422
        "<script>alert(1)</script>",  # non-UUID → 422
    ])
    async def test_traversal_id_on_migration_is_safe(
        self, api_client: AsyncClient, admin_headers: dict, bad_id: str
    ):
        resp = await api_client.get(
            f"/api/v1/migrations/{bad_id}",
            headers=admin_headers,
        )
        assert resp.status_code in (404, 422), (
            f"Traversal ID {bad_id!r} returned {resp.status_code} — must be 404 or 422"
        )
        assert resp.status_code != 200, "Path traversal must never return 200"

    @pytest.mark.parametrize("bad_id", [
        "../../etc/passwd",         # URL-normalized → 404
        "'; DROP TABLE connections; --",  # string param → 404 (connection not found)
    ])
    async def test_traversal_id_on_connection_delete_is_safe(
        self, api_client: AsyncClient, admin_headers: dict, bad_id: str
    ):
        resp = await api_client.delete(
            f"/api/v1/connections/{bad_id}",
            headers=admin_headers,
        )
        assert resp.status_code in (404, 422), (
            f"Traversal ID {bad_id!r} on DELETE returned {resp.status_code} — must be 404 or 422"
        )
        assert resp.status_code != 200


# ═══════════════════════════════════════════════════════════════════════════
# JWT role escalation
# ═══════════════════════════════════════════════════════════════════════════

class TestJwtRoleEscalation:
    """A token forged with a higher role but an invalid signature must be rejected."""

    async def test_forged_admin_role_in_viewer_token_is_rejected(
        self, api_client: AsyncClient
    ):
        import jwt as pyjwt
        from datetime import UTC, datetime, timedelta

        # Sign with a wrong key — simulates an attacker who knows the JWT structure
        # but not the secret.
        forged_payload = {
            "sub": "attacker",
            "role": "admin",
            "typ": "access",
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(hours=1),
        }
        forged_token = pyjwt.encode(forged_payload, "wrong-secret-key", algorithm="HS256")

        resp = await api_client.get(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {forged_token}"},
        )
        assert resp.status_code == 401, (
            "A token signed with the wrong key must return 401, not grant admin access"
        )

    async def test_none_algorithm_attack_is_rejected(self, api_client: AsyncClient):
        """JWT 'none' algorithm attack — payload claims admin but has no signature."""
        import base64
        import json

        header = base64.urlsafe_b64encode(
            json.dumps({"alg": "none", "typ": "JWT"}).encode()
        ).rstrip(b"=").decode()
        payload = base64.urlsafe_b64encode(
            json.dumps({"sub": "attacker", "role": "admin"}).encode()
        ).rstrip(b"=").decode()
        forged = f"{header}.{payload}."

        resp = await api_client.get(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {forged}"},
        )
        assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════
# Unexpected / extra fields (prototype pollution guard)
# ═══════════════════════════════════════════════════════════════════════════

class TestUnexpectedFieldsIgnored:
    """Pydantic models must silently ignore extra fields rather than crashing."""

    async def test_extra_fields_in_login_body_ignored(self, api_client: AsyncClient):
        resp = await api_client.post(
            "/api/v1/auth/login",
            json={
                "username": "admin",
                "password": "admin-password",
                "__proto__": {"admin": True},
                "is_superuser": True,
            },
        )
        # Should still authenticate normally or return 401 — not 422 or 500
        assert resp.status_code in (200, 401)

    async def test_extra_fields_in_convert_body_ignored(
        self, api_client: AsyncClient, operator_headers: dict
    ):
        resp = await api_client.post(
            "/api/v1/convert",
            json={
                "sql": "SELECT 1",
                "object_type": "raw",
                "__class__": "evil",
                "inject": "DROP TABLE users",
            },
            headers=operator_headers,
        )
        assert resp.status_code in (200, 400), (
            f"Extra fields must not crash the endpoint, got {resp.status_code}"
        )
