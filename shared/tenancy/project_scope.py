"""Project / tenant scoping helpers (§13.7).
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from fastapi import HTTPException


def resolve_project_filter(
    requested_project_id: str | None,
    *,
    user_project_id: str | None = None,
    is_admin: bool = False,
) -> str | None:
    """Return the effective project_id filter for list queries.

    Non-admin users are pinned to their JWT ``project_id`` claim.
    Admins may pass an explicit filter or see all (None).
    """
    if is_admin:
        return requested_project_id
    if user_project_id:
        if requested_project_id and requested_project_id != user_project_id:
            raise HTTPException(
                status_code=403,
                detail="Cannot access resources outside your project",
            )
        return user_project_id
    return requested_project_id


def assert_resource_project_access(
    resource_project_id: str | None,
    *,
    user_project_id: str | None = None,
    is_admin: bool = False,
) -> None:
    """Raise 403 when a scoped non-admin user accesses another project's resource.

    Resources without ``project_id`` remain visible (legacy / global rows).
    Admins and unscoped tokens are not restricted.
    """
    if is_admin or not user_project_id:
        return
    if resource_project_id and str(resource_project_id) != str(user_project_id):
        raise HTTPException(
            status_code=403,
            detail="Cannot access resources outside your project",
        )


def connection_in_project(entry: dict, project_id: str | None) -> bool:
    if not project_id:
        return True
    return entry.get("project_id") == project_id
