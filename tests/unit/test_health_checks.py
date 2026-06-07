"""
Module: tests/unit/test_health_checks.py
Purpose: Unit tests for the deep health-check probes and aggregator (Issue #28).
Domain: API / Observability
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from apps.api.health_checks import (
    ProbeResult,
    check_encryption,
    check_metadata_db,
    check_redis,
    run_all_checks,
)


class _FakeSessionCtx:
    def __init__(self, session, raise_on_enter=False):
        self._session = session
        self._raise = raise_on_enter

    async def __aenter__(self):
        if self._raise:
            raise RuntimeError("connect failed")
        return self._session

    async def __aexit__(self, *exc):
        return False


def _session_factory(session=None, raise_on_enter=False):
    def factory():
        return _FakeSessionCtx(session, raise_on_enter=raise_on_enter)
    return factory


class _OkSecrets:
    def encrypt(self, s: str) -> str:
        return f"enc::{s}"

    def decrypt(self, s: str) -> str:
        return s.removeprefix("enc::")


class _BrokenSecrets:
    def encrypt(self, s: str) -> str:
        raise RuntimeError("no key")

    def decrypt(self, s: str) -> str:  # pragma: no cover
        raise RuntimeError("no key")


class TestMetadataDbProbe:
    @pytest.mark.asyncio
    async def test_healthy_when_query_succeeds(self):
        session = AsyncMock()
        session.execute = AsyncMock(return_value=None)
        result = await check_metadata_db(_session_factory(session))
        assert isinstance(result, ProbeResult)
        assert result.healthy is True
        assert result.name == "metadata_db"

    @pytest.mark.asyncio
    async def test_unhealthy_when_connection_fails(self):
        result = await check_metadata_db(_session_factory(raise_on_enter=True))
        assert result.healthy is False
        assert "connect failed" in result.detail


class TestEncryptionProbe:
    def test_healthy_on_roundtrip(self):
        result = check_encryption(_OkSecrets())
        assert result.healthy is True
        assert result.name == "encryption"

    def test_unhealthy_when_secrets_unavailable(self):
        assert check_encryption(None).healthy is False

    def test_unhealthy_on_encrypt_error(self):
        assert check_encryption(_BrokenSecrets()).healthy is False


class TestRedisProbe:
    @pytest.mark.asyncio
    async def test_skipped_when_no_client(self):
        result = await check_redis(None)
        # A skipped optional dependency is not a failure.
        assert result.healthy is True
        assert "skip" in result.detail.lower()

    @pytest.mark.asyncio
    async def test_healthy_on_ping(self):
        client = AsyncMock()
        client.ping = AsyncMock(return_value=True)
        result = await check_redis(client)
        assert result.healthy is True

    @pytest.mark.asyncio
    async def test_unhealthy_on_ping_failure(self):
        client = AsyncMock()
        client.ping = AsyncMock(side_effect=RuntimeError("down"))
        result = await check_redis(client)
        assert result.healthy is False


class TestAggregator:
    @pytest.mark.asyncio
    async def test_all_healthy(self):
        session = AsyncMock()
        session.execute = AsyncMock(return_value=None)
        report = await run_all_checks(
            session_factory=_session_factory(session),
            secrets_manager=_OkSecrets(),
            redis_client=None,
        )
        assert report["healthy"] is True
        assert set(report["checks"]) == {"metadata_db", "encryption", "redis"}

    @pytest.mark.asyncio
    async def test_unhealthy_if_any_probe_fails(self):
        report = await run_all_checks(
            session_factory=_session_factory(raise_on_enter=True),
            secrets_manager=_OkSecrets(),
            redis_client=None,
        )
        assert report["healthy"] is False
        assert report["checks"]["metadata_db"]["healthy"] is False
        assert report["checks"]["encryption"]["healthy"] is True


class TestDeepHealthEndpoint:
    @pytest.mark.asyncio
    async def test_endpoint_is_public_and_reports_checks(self, bare_api_client):
        """/health/deep is reachable without auth and returns per-dependency
        status. With a working in-memory DB + encryption it is healthy (200)."""
        resp = await bare_api_client.get("/health/deep")
        assert resp.status_code == 200
        body = resp.json()
        assert body["healthy"] is True
        assert set(body["checks"]) == {"metadata_db", "encryption", "redis"}
        assert "timestamp" in body
