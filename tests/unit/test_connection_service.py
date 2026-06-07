"""
Module: tests/unit/test_connection_service.py
Purpose: Unit tests for ConnectionService — creation, DTO conversion,
         encryption round-trip, and update/delete flows.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from application.connection_service import (
    ConnectionCreateRequest,
    ConnectionService,
    ConnectionServiceError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_record(
    id_: str = "conn-1",
    name: str = "src",
    db_type: str = "sqlserver",
    encrypted_password: str = "enc:secret",
) -> MagicMock:
    r = MagicMock()
    r.project_connection_id = id_
    r.name = name
    r.db_type = db_type
    r.host = "localhost"
    r.port = 1433
    r.database_name = "AdventureWorks"
    r.username = "sa"
    r.encrypted_password = encrypted_password
    r.ssl_enabled = False
    r.created_at = datetime.now(UTC)
    r.last_tested_at = None
    r.last_test_ok = None
    return r


def _make_service(records: list = None):  # type: ignore[no-untyped-def]
    secrets = MagicMock()
    secrets.encrypt = MagicMock(return_value="enc:secret")
    secrets.decrypt = MagicMock(return_value="plain_password")

    session = MagicMock()
    session.flush = AsyncMock()
    session.add = MagicMock()

    svc = ConnectionService(session, secrets)
    svc._repo = MagicMock()
    svc._repo.get_all = AsyncMock(return_value=records or [])
    svc._repo.get_by_id = AsyncMock(return_value=None)
    svc._repo.create = AsyncMock(return_value=_make_record())
    svc._repo.update = AsyncMock(return_value=_make_record())
    svc._repo.delete = AsyncMock(return_value=True)
    svc._repo.update_test_status = AsyncMock()
    return svc, secrets


# ---------------------------------------------------------------------------
# _to_dto
# ---------------------------------------------------------------------------


class TestConnectionServiceToDto:
    def test_dto_fields_match_record(self):
        record = _make_record()
        dto = ConnectionService._to_dto(record)
        assert dto.id == record.project_connection_id
        assert dto.name == record.name
        assert dto.db_type == record.db_type
        assert dto.host == record.host
        assert dto.port == record.port
        assert dto.username == record.username
        assert dto.ssl_enabled is False
        assert dto.last_tested_at is None
        assert dto.last_test_ok is None

    def test_dto_created_at_is_iso_string(self):
        record = _make_record()
        dto = ConnectionService._to_dto(record)
        assert "T" in dto.created_at  # ISO-8601


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


class TestConnectionServiceCreate:
    @pytest.mark.asyncio
    async def test_create_encrypts_password(self):
        svc, secrets = _make_service()
        req = ConnectionCreateRequest(
            name="src", db_type="sqlserver",
            host="localhost", port=1433,
            database_name="TestDB", username="sa", password="secret",
        )
        await svc.create(req)
        secrets.encrypt.assert_called_once_with("secret")

    @pytest.mark.asyncio
    async def test_create_invalid_db_type_raises(self):
        svc, _ = _make_service()
        req = ConnectionCreateRequest(
            name="x", db_type="mysql",
            host="h", port=3306,
            database_name="db", username="u", password="p",
        )
        with pytest.raises(ConnectionServiceError, match="db_type"):
            await svc.create(req)

    @pytest.mark.asyncio
    async def test_create_returns_dto(self):
        svc, _ = _make_service()
        req = ConnectionCreateRequest(
            name="src", db_type="sqlserver",
            host="localhost", port=1433,
            database_name="DB", username="sa", password="p",
        )
        dto = await svc.create(req)
        assert dto.id == "conn-1"

    @pytest.mark.asyncio
    async def test_create_empty_password_not_encrypted(self):
        svc, secrets = _make_service()
        req = ConnectionCreateRequest(
            name="src", db_type="postgresql",
            host="localhost", port=5432,
            database_name="pg", username="postgres", password="",
        )
        await svc.create(req)
        secrets.encrypt.assert_not_called()


# ---------------------------------------------------------------------------
# decrypt_password
# ---------------------------------------------------------------------------


class TestDecryptPassword:
    @pytest.mark.asyncio
    async def test_decrypt_returns_plaintext(self):
        svc, secrets = _make_service()
        svc._repo.get_by_id = AsyncMock(return_value=_make_record())
        result = await svc.decrypt_password("conn-1")
        assert result == "plain_password"

    @pytest.mark.asyncio
    async def test_decrypt_missing_connection_raises(self):
        svc, _ = _make_service()
        svc._repo.get_by_id = AsyncMock(return_value=None)
        with pytest.raises(ConnectionServiceError, match="not found"):
            await svc.decrypt_password("missing")


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


class TestConnectionServiceDelete:
    @pytest.mark.asyncio
    async def test_delete_missing_raises(self):
        svc, _ = _make_service()
        svc._repo.delete = AsyncMock(return_value=False)
        with pytest.raises(ConnectionServiceError, match="not found"):
            await svc.delete("missing")

    @pytest.mark.asyncio
    async def test_delete_existing_succeeds(self):
        svc, _ = _make_service()
        svc._repo.delete = AsyncMock(return_value=True)
        await svc.delete("conn-1")  # should not raise


# ---------------------------------------------------------------------------
# list_all / get_by_id
# ---------------------------------------------------------------------------


class TestConnectionServiceQuery:
    @pytest.mark.asyncio
    async def test_list_all_returns_dtos(self):
        svc, _ = _make_service(records=[_make_record("a"), _make_record("b")])
        dtos = await svc.list_all()
        assert len(dtos) == 2

    @pytest.mark.asyncio
    async def test_get_by_id_missing_raises(self):
        svc, _ = _make_service()
        svc._repo.get_by_id = AsyncMock(return_value=None)
        with pytest.raises(ConnectionServiceError, match="not found"):
            await svc.get_by_id("bad-id")

    @pytest.mark.asyncio
    async def test_get_by_id_found_returns_dto(self):
        svc, _ = _make_service()
        svc._repo.get_by_id = AsyncMock(return_value=_make_record())
        dto = await svc.get_by_id("conn-1")
        assert dto.name == "src"
