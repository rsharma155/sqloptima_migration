# Author: Ravi Sharma
# Copyright (c) 2026 Ravi Sharma
# SPDX-License-Identifier: MIT

"""L-16 API E2E: discover → migrate → validate via HTTP.

Uses the ASGI ``api_client`` fixture (no live SQL Server required for the
happy-path scaffolding). When ``MIGRATION_E2E_LIVE=1`` and source/target env
vars are set, the live branch exercises real discovery against SQL Server.
"""

from __future__ import annotations

import os

import pytest
from httpx import AsyncClient

LIVE = os.environ.get("MIGRATION_E2E_LIVE", "").strip() in {"1", "true", "TRUE"}


@pytest.mark.asyncio
async def test_discover_migrate_validate_api_flow(
    api_client: AsyncClient,
    operator_headers: dict[str, str],
) -> None:
    """API lifecycle: list connections → create migration → list → validate path."""

    # 1) Auth'd connections list (discover prerequisites)
    conn_resp = await api_client.get("/api/v1/connections", headers=operator_headers)
    assert conn_resp.status_code == 200
    assert isinstance(conn_resp.json(), list)

    # 2) Discover endpoint — without a live SQL Server expect client/gateway error, not unhandled 5xx crash
    discover_resp = await api_client.post(
        "/api/v1/discover",
        headers=operator_headers,
        json={"connection_id": "00000000-0000-0000-0000-000000000001", "schema": "dbo"},
    )
    # 404 (unknown connection), 4xx validation, or 502 (source unreachable) are all acceptable
    assert discover_resp.status_code in {200, 400, 404, 422, 502}

    # 3) Create a migration job (engine may reject without live DBs — accept 2xx/4xx/502)
    mig_payload = {
        "source_connection_id": "00000000-0000-0000-0000-000000000001",
        "target_connection_id": "00000000-0000-0000-0000-000000000002",
        "tables": ["users"],
        "require_target_snapshot": False,
    }
    mig_resp = await api_client.post(
        "/api/v1/migrations",
        headers=operator_headers,
        json=mig_payload,
    )
    assert mig_resp.status_code in {200, 201, 400, 404, 422, 502}

    # 4) List migrations
    list_resp = await api_client.get("/api/v1/migrations", headers=operator_headers)
    assert list_resp.status_code == 200

    # 5) Validation endpoint contract
    val_resp = await api_client.post(
        "/api/v1/validate",
        headers=operator_headers,
        json={
            "source_connection_id": "00000000-0000-0000-0000-000000000001",
            "target_connection_id": "00000000-0000-0000-0000-000000000002",
            "tables": ["users"],
        },
    )
    assert val_resp.status_code in {200, 201, 400, 404, 422, 502}


@pytest.mark.asyncio
@pytest.mark.skipif(not LIVE, reason="Set MIGRATION_E2E_LIVE=1 for live SQL Server/Postgres")
async def test_live_discover_migrate_validate(
    api_client: AsyncClient,
    operator_headers: dict[str, str],
) -> None:
    """Live discover → migrate → validate when sample DBs are available."""
    source_id = os.environ.get("MIGRATION_E2E_SOURCE_CONNECTION_ID")
    target_id = os.environ.get("MIGRATION_E2E_TARGET_CONNECTION_ID")
    if not source_id or not target_id:
        pytest.skip("MIGRATION_E2E_SOURCE_CONNECTION_ID / TARGET_CONNECTION_ID required")

    discover = await api_client.post(
        "/api/v1/discover",
        headers=operator_headers,
        json={"connection_id": source_id, "schema": "dbo"},
    )
    assert discover.status_code == 200
    tables = discover.json().get("tables") or []
    assert tables, "expected at least one discovered table"

    table_names = [t["name"] if isinstance(t, dict) else t for t in tables[:1]]
    mig = await api_client.post(
        "/api/v1/migrations",
        headers=operator_headers,
        json={
            "source_connection_id": source_id,
            "target_connection_id": target_id,
            "tables": table_names,
            "require_target_snapshot": False,
        },
    )
    assert mig.status_code in {200, 201}
    job_id = mig.json().get("job_id") or mig.json().get("id")
    assert job_id

    val = await api_client.post(
        "/api/v1/validate",
        headers=operator_headers,
        json={
            "source_connection_id": source_id,
            "target_connection_id": target_id,
            "tables": table_names,
            "job_id": job_id,
        },
    )
    assert val.status_code == 200
