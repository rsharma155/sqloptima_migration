"""Unit tests for project / tenant scoping helpers (§13.7)."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from shared.tenancy.project_scope import (
    assert_resource_project_access,
    resolve_project_filter,
)


def test_resolve_project_filter_pins_non_admin():
    assert resolve_project_filter(None, user_project_id="p1", is_admin=False) == "p1"
    assert resolve_project_filter("p1", user_project_id="p1", is_admin=False) == "p1"
    with pytest.raises(HTTPException) as exc:
        resolve_project_filter("p2", user_project_id="p1", is_admin=False)
    assert exc.value.status_code == 403


def test_resolve_project_filter_admin_unrestricted():
    assert resolve_project_filter(None, user_project_id="p1", is_admin=True) is None
    assert resolve_project_filter("p2", user_project_id="p1", is_admin=True) == "p2"


def test_assert_resource_project_access_blocks_cross_tenant():
    assert_resource_project_access("p1", user_project_id="p1", is_admin=False)
    assert_resource_project_access(None, user_project_id="p1", is_admin=False)
    with pytest.raises(HTTPException) as exc:
        assert_resource_project_access("p2", user_project_id="p1", is_admin=False)
    assert exc.value.status_code == 403
