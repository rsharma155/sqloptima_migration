"""Metadata database security audit (§12.8).
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.metadata_db.repositories.connection_repository import ConnectionRepository
from shared.security.secrets_manager import SecretsManager


@dataclass
class MetadataSecurityReport:
    master_key_configured: bool
    metadata_db_url: str
    connection_count: int
    encrypted_credential_count: int
    vault_ref_count: int
    plaintext_credential_count: int
    issues: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "master_key_configured": self.master_key_configured,
            "metadata_db_url": self.metadata_db_url,
            "connection_count": self.connection_count,
            "encrypted_credential_count": self.encrypted_credential_count,
            "vault_ref_count": self.vault_ref_count,
            "plaintext_credential_count": self.plaintext_credential_count,
            "issues": self.issues,
            "recommendations": self.recommendations,
            "compliant": self.plaintext_credential_count == 0 and self.master_key_configured,
        }


def _looks_encrypted(password_field: str) -> bool:
    if not password_field:
        return True
    if password_field.startswith("v2:"):
        return True
    if ":" in password_field and len(password_field) > 40:
        return True
    return False


class MetadataSecurityService:
    """Verify credentials are stored as ciphertext, not plaintext."""

    async def audit(self, session: AsyncSession) -> MetadataSecurityReport:
        repo = ConnectionRepository(session)
        records = await repo.get_all()
        master_set = bool(os.environ.get("MIGRATION_MASTER_KEY", "").strip())
        db_url = os.environ.get("METADATA_DB_URL", "sqlite (default local file)")

        encrypted = vault = plaintext = 0
        issues: list[str] = []
        for rec in records:
            if rec.vault_ref:
                vault += 1
                continue
            if not rec.encrypted_password:
                continue
            if _looks_encrypted(rec.encrypted_password):
                encrypted += 1
            else:
                plaintext += 1
                issues.append(
                    f"Connection '{rec.name}' ({rec.project_connection_id}) stores a plaintext password"
                )

        recommendations = [
            "Store MIGRATION_MASTER_KEY outside the metadata DB (K8s secret / vault).",
            "Place SQLite metadata files on an encrypted volume with restricted permissions.",
            "Prefer METADATA_DB_URL pointing to TLS-enabled PostgreSQL for multi-node deployments.",
            "Use vault_ref on connections when SECRET_PROVIDER is configured.",
        ]
        if not master_set:
            issues.append("MIGRATION_MASTER_KEY is not set")
        if plaintext > 0:
            issues.append(
                f"{plaintext} connection(s) have plaintext passwords — re-save via API to encrypt"
            )

        return MetadataSecurityReport(
            master_key_configured=master_set,
            metadata_db_url=db_url.split("@")[-1] if "@" in db_url else db_url,
            connection_count=len(records),
            encrypted_credential_count=encrypted,
            vault_ref_count=vault,
            plaintext_credential_count=plaintext,
            issues=issues,
            recommendations=recommendations,
        )

    @staticmethod
    def verify_master_key_strength() -> None:
        """Raise if master key missing or too short (startup guard)."""
        SecretsManager()
