"""Product editions and feature gates (§13.8).
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import os
from enum import StrEnum


class ProductEdition(StrEnum):
    ASSESS = "assess"
    MIGRATE = "migrate"
    REPLICATE = "replicate"
    ENTERPRISE = "enterprise"


_EDITION_FEATURES: dict[ProductEdition, set[str]] = {
    ProductEdition.ASSESS: {"discovery", "assessment", "reports"},
    ProductEdition.MIGRATE: {"discovery", "assessment", "reports", "migration", "validation", "transfer"},
    ProductEdition.REPLICATE: {
        "discovery", "assessment", "reports", "migration", "validation", "replication", "cutover", "transfer",
    },
    ProductEdition.ENTERPRISE: {
        "discovery", "assessment", "reports", "migration", "validation",
        "replication", "cutover", "programs", "multi_project", "audit_export", "transfer",
    },
}


def current_edition() -> ProductEdition:
    raw = os.environ.get("MIGRATION_EDITION", "enterprise").lower()
    try:
        return ProductEdition(raw)
    except ValueError:
        return ProductEdition.ENTERPRISE


def edition_info() -> dict:
    edition = current_edition()
    return {
        "edition": edition.value,
        "features": sorted(_EDITION_FEATURES[edition]),
        "deployment": os.environ.get("MIGRATION_DEPLOYMENT", "on-prem"),
        "version": os.environ.get("MIGRATION_PLATFORM_VERSION", "0.2.1"),
    }


def require_feature(feature: str) -> None:
    edition = current_edition()
    if feature not in _EDITION_FEATURES[edition]:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=403,
            detail=f"Feature '{feature}' requires a higher edition than '{edition.value}'",
        )
