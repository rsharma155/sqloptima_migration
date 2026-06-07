"""Connection store — DB-backed (via ConnectionRepository) with an in-memory cache.

The in-memory dict is the hot path; the DB is the durable store.
All writes go to both. The cache is populated from DB at startup.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from infrastructure.metadata_db.models import ConnectionRecord
from infrastructure.metadata_db.repositories import ConnectionRepository
from infrastructure.metadata_db.session import AsyncSessionFactory
from shared.logging.structured_logging import get_logger
from shared.security.secret_provider import SecretProvider
from shared.security.secrets_manager import SecretsManager

logger = get_logger(__name__)

# In-memory cache: keyed by connection ID string.
_connections: dict[str, dict] = {}
_secrets_instance: SecretsManager | None = None
_secret_provider: SecretProvider | None = None


def set_secrets_manager(sm: SecretsManager | None) -> None:
    global _secrets_instance
    _secrets_instance = sm


def set_secret_provider(sp: SecretProvider | None) -> None:
    global _secret_provider
    _secret_provider = sp


async def load_connections() -> None:
    """Populate the in-memory cache from the DB. Called once at startup."""
    try:
        async with AsyncSessionFactory() as session:
            repo = ConnectionRepository(session)
            records = await repo.get_all()
        _connections.clear()
        for r in records:
            _connections[r.project_connection_id] = _record_to_dict(r)
        logger.info("Connections loaded from DB", count=len(_connections))
    except Exception as exc:
        logger.warning("Failed to load connections from DB, starting empty", error=str(exc))
        _connections.clear()


def _record_to_dict(r: ConnectionRecord) -> dict:
    return {
        "name": r.name,
        "type": r.db_type,
        "host": r.host,
        "port": r.port,
        "database": r.database_name,
        "username": r.username,
        "password": r.encrypted_password,
        "vault_ref": r.vault_ref,
        "project_id": r.project_id,
        "trust_server_certificate": bool(r.ssl_enabled),
        "status": "connected" if r.last_test_ok else "disconnected",
        "created_at": r.created_at.isoformat() if r.created_at else "",
    }


def _dict_to_record(connection_id: str, entry: dict) -> ConnectionRecord:
    trust = entry.get("trust_server_certificate", entry.get("ssl_enabled", False))
    return ConnectionRecord(
        project_connection_id=connection_id,
        name=entry.get("name", ""),
        db_type=entry.get("type", ""),
        host=entry.get("host", ""),
        port=int(entry.get("port", 5432)),
        database_name=entry.get("database", ""),
        username=entry.get("username", ""),
        encrypted_password=entry.get("password", ""),
        vault_ref=entry.get("vault_ref"),
        project_id=entry.get("project_id"),
        ssl_enabled=bool(trust),
        created_at=datetime.fromisoformat(entry["created_at"])
        if entry.get("created_at")
        else datetime.now(UTC),
    )


async def _persist(connection_id: str, entry: dict) -> None:
    try:
        async with AsyncSessionFactory() as session:
            repo = ConnectionRepository(session)
            await repo.upsert(_dict_to_record(connection_id, entry))
    except Exception as exc:
        logger.error("Failed to persist connection to DB", connection_id=connection_id, error=str(exc))


async def _delete_persisted(connection_id: str) -> bool:
    try:
        async with AsyncSessionFactory() as session:
            repo = ConnectionRepository(session)
            deleted = await repo.delete(connection_id)
            if deleted:
                await session.commit()
            return deleted
    except Exception as exc:
        logger.error("Failed to delete connection from DB", connection_id=connection_id, error=str(exc))
        return False


# ---------------------------------------------------------------------------
# Public API used by main.py
# ---------------------------------------------------------------------------

def get_all(project_id: str | None = None) -> dict[str, dict]:
    if not project_id:
        return _connections
    return {
        cid: entry
        for cid, entry in _connections.items()
        if entry.get("project_id") == project_id
    }


def get_entry(connection_id: str) -> dict | None:
    return _connections.get(connection_id)


def set_entry(connection_id: str, entry: dict) -> None:
    _connections[connection_id] = entry


def remove_entry(connection_id: str) -> None:
    _connections.pop(connection_id, None)


async def save_connection_async(connection_id: str) -> None:
    """Persist a single connection from the in-memory cache to DB."""
    entry = _connections.get(connection_id)
    if entry:
        await _persist(connection_id, entry)


async def save_connections_async() -> None:
    """Persist ALL in-memory connections to DB (upsert). Used for bulk sync."""
    for cid, entry in list(_connections.items()):
        await _persist(cid, entry)


async def delete_connection_async(connection_id: str) -> bool:
    """Remove a connection from both cache and DB. Returns True if removed from cache or DB."""
    had_cache = connection_id in _connections
    _connections.pop(connection_id, None)
    deleted_db = await _delete_persisted(connection_id)
    return had_cache or deleted_db


def get_decrypted_password(entry: dict) -> str:
    # vault_ref takes priority: resolve from the external secret manager.
    vault_ref = entry.get("vault_ref")
    if vault_ref and _secret_provider:
        try:
            return _secret_provider.resolve(vault_ref)
        except Exception as exc:
            logger.warning("Failed to resolve vault_ref, falling back to encrypted_password", error=str(exc))

    # Fall back to the Fernet-encrypted value stored in the metadata DB.
    pw = entry.get("password", "")
    if _secrets_instance and pw and ":" in pw:
        try:
            return _secrets_instance.decrypt(pw)
        except Exception:
            logger.warning("Failed to decrypt password, returning as-is")
    return pw


async def update_test_status_async(connection_id: str, *, ok: bool) -> None:
    """Update the last_test_ok flag both in-memory and in the DB."""
    entry = _connections.get(connection_id)
    if entry:
        entry["status"] = "connected" if ok else "error"
    try:
        async with AsyncSessionFactory() as session:
            repo = ConnectionRepository(session)
            await repo.update_test_status(connection_id, ok=ok)
    except Exception as exc:
        logger.error("Failed to update test status in DB", connection_id=connection_id, error=str(exc))
