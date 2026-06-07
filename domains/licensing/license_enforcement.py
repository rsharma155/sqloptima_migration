"""License key validation and edition enforcement (§13.8).
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import hashlib
import hmac
import os

from domains.licensing.editions import ProductEdition, current_edition


def _license_secret() -> str:
    return os.environ.get(
        "MIGRATION_LICENSE_SECRET",
        os.environ.get("MIGRATION_MASTER_KEY", "dev-license-secret"),
    )


def generate_license_key(edition: ProductEdition, org_id: str = "default") -> str:
    """Generate an HMAC license token for an edition (operator tooling)."""
    payload = f"{edition.value}:{org_id}"
    sig = hmac.new(
        _license_secret().encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()[:24]
    return f"{edition.value.upper()}-{sig}"


def validate_license_key(key: str | None = None) -> tuple[bool, str]:
    """Return (valid, message). DEV-LOCAL and matching HMAC keys are accepted."""
    license_key = key or os.environ.get("MIGRATION_LICENSE_KEY", "DEV-LOCAL")
    if license_key in ("DEV-LOCAL", ""):
        if os.environ.get("MIGRATION_ENV") == "production":
            return False, "DEV-LOCAL license not permitted in production"
        return True, "development license"

    edition = current_edition()
    expected = generate_license_key(edition)
    if hmac.compare_digest(license_key, expected):
        return True, f"valid license for {edition.value}"

    for ed in ProductEdition:
        if hmac.compare_digest(license_key, generate_license_key(ed)):
            if ed != edition:
                return False, f"license is for '{ed.value}' but MIGRATION_EDITION is '{edition.value}'"
            return True, f"valid license for {ed.value}"

    return False, "invalid or expired license key"


def require_valid_license() -> None:
    from fastapi import HTTPException

    ok, msg = validate_license_key()
    if not ok:
        raise HTTPException(status_code=403, detail=f"License validation failed: {msg}")
