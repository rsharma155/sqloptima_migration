"""Tests for project tenancy scoping (§13.7)."""
import pytest
from fastapi import HTTPException

from shared.tenancy.project_scope import connection_in_project, resolve_project_filter


def test_admin_can_filter_any_project():
    assert resolve_project_filter("proj-1", is_admin=True) == "proj-1"
    assert resolve_project_filter(None, is_admin=True) is None


def test_user_pinned_to_jwt_project():
    assert resolve_project_filter(None, user_project_id="proj-a") == "proj-a"


def test_user_cannot_access_other_project():
    with pytest.raises(HTTPException) as exc:
        resolve_project_filter("proj-b", user_project_id="proj-a", is_admin=False)
    assert exc.value.status_code == 403


def test_connection_in_project_filter():
    assert connection_in_project({"project_id": "p1"}, "p1") is True
    assert connection_in_project({"project_id": "p1"}, "p2") is False
    assert connection_in_project({"project_id": "p1"}, None) is True
