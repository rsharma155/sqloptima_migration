"""
Module: access_control.py
Purpose: Encryption and secrets management
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)


class Permission(StrEnum):
    MIGRATION_START = "migration:start"
    MIGRATION_STOP = "migration:stop"
    MIGRATION_PAUSE = "migration:pause"
    MIGRATION_RESUME = "migration:resume"
    MIGRATION_READ = "migration:read"
    MIGRATION_WRITE = "migration:write"
    MIGRATION_DELETE = "migration:delete"
    DISCOVERY_START = "discovery:start"
    DISCOVERY_READ = "discovery:read"
    CONVERSION_START = "conversion:start"
    CONVERSION_READ = "conversion:read"
    VALIDATION_START = "validation:start"
    VALIDATION_READ = "validation:read"
    CONFIG_READ = "config:read"
    CONFIG_WRITE = "config:write"
    AUDIT_READ = "audit:read"
    USER_ADMIN = "user:admin"
    USER_READ = "user:read"


class Role(StrEnum):
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"
    AUDITOR = "auditor"


ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.ADMIN: set(Permission),
    Role.OPERATOR: {
        Permission.MIGRATION_START,
        Permission.MIGRATION_STOP,
        Permission.MIGRATION_PAUSE,
        Permission.MIGRATION_RESUME,
        Permission.MIGRATION_READ,
        Permission.MIGRATION_WRITE,
        Permission.DISCOVERY_START,
        Permission.DISCOVERY_READ,
        Permission.CONVERSION_START,
        Permission.CONVERSION_READ,
        Permission.VALIDATION_START,
        Permission.VALIDATION_READ,
        Permission.CONFIG_READ,
    },
    Role.VIEWER: {
        Permission.MIGRATION_READ,
        Permission.DISCOVERY_READ,
        Permission.CONVERSION_READ,
        Permission.VALIDATION_READ,
        Permission.CONFIG_READ,
    },
    Role.AUDITOR: {
        Permission.AUDIT_READ,
        Permission.MIGRATION_READ,
        Permission.DISCOVERY_READ,
        Permission.CONVERSION_READ,
        Permission.VALIDATION_READ,
    },
}


class UserPrincipal(BaseModel):
    user_id: str
    username: str
    roles: list[Role] = Field(default_factory=list)
    permissions: set[Permission] = Field(default_factory=set)

    def has_permission(self, permission: Permission) -> bool:
        return permission in self.permissions

    def has_role(self, role: Role) -> bool:
        return role in self.roles

    def resolve_permissions(self) -> None:
        resolved: set[Permission] = set()
        for role in self.roles:
            resolved.update(ROLE_PERMISSIONS.get(role, set()))
        self.permissions = resolved


class AccessDeniedError(Exception):
    def __init__(self, permission: Permission, user_id: str):
        self.permission = permission
        self.user_id = user_id
        super().__init__(f"Access denied: user '{user_id}' lacks permission '{permission.value}'")


class AccessControl:
    def __init__(self):
        self._users: dict[str, UserPrincipal] = {}

    def register_user(self, principal: UserPrincipal) -> None:
        principal.resolve_permissions()
        self._users[principal.user_id] = principal

    def get_user(self, user_id: str) -> UserPrincipal | None:
        return self._users.get(user_id)

    def check_permission(self, user_id: str, permission: Permission) -> bool:
        user = self._users.get(user_id)
        if not user:
            return False
        return user.has_permission(permission)

    def require_permission(self, user_id: str, permission: Permission) -> None:
        if not self.check_permission(user_id, permission):
            raise AccessDeniedError(permission, user_id)

    def require_role(self, user_id: str, role: Role) -> None:
        user = self._users.get(user_id)
        if not user or not user.has_role(role):
            raise AccessDeniedError(Permission.USER_ADMIN, user_id)


def require_permission(permission: Permission):
    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        async def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            user_id = kwargs.get("user_id") or getattr(self, "_current_user_id", None)
            if not user_id:
                raise AccessDeniedError(permission, "unknown")
            ac: AccessControl | None = getattr(self, "_access_control", None)
            if ac:
                ac.require_permission(user_id, permission)
            return await func(self, *args, **kwargs)
        return wrapper
    return decorator
