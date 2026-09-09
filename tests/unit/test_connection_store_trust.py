"""Unit tests for connection_store trust certificate persistence."""

from __future__ import annotations

from datetime import UTC, datetime

from apps.api.connection_store import _dict_to_record, _record_to_dict
from infrastructure.metadata_db.models import ConnectionRecord


def test_record_to_dict_maps_ssl_enabled_to_trust_server_certificate() -> None:
    record = ConnectionRecord(
        project_connection_id="abc",
        name="SQL Server",
        db_type="source",
        host="localhost",
        port=1433,
        database_name="master",
        username="sa",
        encrypted_password="enc",
        ssl_enabled=True,
        created_at=datetime.now(UTC),
    )
    d = _record_to_dict(record)
    assert d["trust_server_certificate"] is True
    assert d.get("engine") is None or d.get("engine") in {None, "sqlserver"}


def test_dict_to_record_persists_trust_server_certificate_as_ssl_enabled() -> None:
    record = _dict_to_record(
        "abc",
        {
            "name": "SQL Server",
            "type": "source",
            "host": "localhost",
            "port": 1433,
            "database": "master",
            "username": "sa",
            "password": "enc",
            "trust_server_certificate": True,
            "created_at": datetime.now(UTC).isoformat(),
        },
    )
    assert record.ssl_enabled is True


def test_dict_to_record_trust_defaults_false() -> None:
    record = _dict_to_record(
        "abc",
        {
            "name": "SQL Server",
            "type": "source",
            "host": "localhost",
            "port": 1433,
            "database": "master",
            "username": "sa",
            "password": "enc",
            "created_at": datetime.now(UTC).isoformat(),
        },
    )
    assert record.ssl_enabled is False
