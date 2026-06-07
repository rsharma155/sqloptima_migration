"""Security and encryption utilities.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from shared.security.access_control import (
    AccessControl,
    AccessDeniedError,
    Permission,
    Role,
    ROLE_PERMISSIONS,
    UserPrincipal,
    require_permission,
)
from shared.security.audit_log import AuditAction, AuditLogEntry, AuditLogger, AUDIT_LOG_DDL
from shared.security.secrets_manager import SecretsManager

__all__ = [
    "AccessControl",
    "AccessDeniedError",
    "Permission",
    "Role",
    "ROLE_PERMISSIONS",
    "UserPrincipal",
    "require_permission",
    "AuditAction",
    "AuditLogEntry",
    "AuditLogger",
    "AUDIT_LOG_DDL",
    "SecretsManager",
]
