"""
Module: apps/api/middleware/auth.py
Purpose: JWT authentication middleware + role-based access control for FastAPI
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, Callable

import uuid

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

JWT_SECRET = os.environ.get("MIGRATION_JWT_SECRET")
if not JWT_SECRET:
    raise RuntimeError(
        "MIGRATION_JWT_SECRET environment variable is required. "
        "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
    )
JWT_SECRET_PREVIOUS = os.environ.get("MIGRATION_JWT_SECRET_PREVIOUS")

# Optional RS256 (§12.5): when both PEM keys are set, issue/verify with RS256.
# HS256 + dual-secret rotation remains the default for single-node deployments.
JWT_PRIVATE_KEY = os.environ.get("MIGRATION_JWT_PRIVATE_KEY", "").replace("\\n", "\n").strip() or None
JWT_PUBLIC_KEY = os.environ.get("MIGRATION_JWT_PUBLIC_KEY", "").replace("\\n", "\n").strip() or None
JWT_PUBLIC_KEY_PREVIOUS = (
    os.environ.get("MIGRATION_JWT_PUBLIC_KEY_PREVIOUS", "").replace("\\n", "\n").strip() or None
)

if bool(JWT_PRIVATE_KEY) != bool(JWT_PUBLIC_KEY):
    raise RuntimeError(
        "Set both MIGRATION_JWT_PRIVATE_KEY and MIGRATION_JWT_PUBLIC_KEY for RS256, "
        "or neither to keep HS256."
    )

JWT_ALGORITHM = "RS256" if JWT_PRIVATE_KEY and JWT_PUBLIC_KEY else "HS256"
ACCESS_TOKEN_EXPIRY_HOURS = 8
REFRESH_TOKEN_EXPIRY_DAYS = 7

# Keep for backward compatibility with any callers that import this name.
JWT_EXPIRY_HOURS = ACCESS_TOKEN_EXPIRY_HOURS

security_scheme = HTTPBearer(auto_error=False)


def _signing_key() -> str:
    if JWT_ALGORITHM == "RS256":
        assert JWT_PRIVATE_KEY is not None
        return JWT_PRIVATE_KEY
    return JWT_SECRET


def _encode(payload: dict[str, Any]) -> str:
    return jwt.encode(payload, _signing_key(), algorithm=JWT_ALGORITHM)


def _hs_secrets() -> list[str]:
    secrets: list[str] = [JWT_SECRET]
    if JWT_SECRET_PREVIOUS and JWT_SECRET_PREVIOUS != JWT_SECRET:
        secrets.append(JWT_SECRET_PREVIOUS)
    return secrets


def _verification_keys() -> list[str]:
    """Primary verification material for the active algorithm (current, then previous)."""
    if JWT_ALGORITHM == "RS256":
        keys: list[str] = []
        if JWT_PUBLIC_KEY:
            keys.append(JWT_PUBLIC_KEY)
        if JWT_PUBLIC_KEY_PREVIOUS and JWT_PUBLIC_KEY_PREVIOUS != JWT_PUBLIC_KEY:
            keys.append(JWT_PUBLIC_KEY_PREVIOUS)
        return keys
    return _hs_secrets()


def _verification_secrets() -> list[str]:
    """Backward-compat alias used by HS256 rotation tests."""
    return _hs_secrets()


def _decode_attempts() -> list[tuple[str, str]]:
    """(key, algorithm) pairs tried in order when verifying a token."""
    if JWT_ALGORITHM == "RS256":
        attempts = [(key, "RS256") for key in _verification_keys()]
        # Accept HS256 tokens during RS256 rollout so existing sessions keep working.
        attempts.extend((secret, "HS256") for secret in _hs_secrets())
        return attempts
    return [(secret, "HS256") for secret in _hs_secrets()]


def _decode(token: str) -> dict[str, Any]:
    expired = False
    for key, alg in _decode_attempts():
        try:
            return jwt.decode(token, key, algorithms=[alg])
        except jwt.ExpiredSignatureError:
            expired = True
        except jwt.InvalidTokenError:
            continue
    if expired:
        raise HTTPException(status_code=401, detail="Token expired")
    raise HTTPException(status_code=401, detail="Invalid token")


def create_access_token(
    user_id: str,
    role: str,
    *,
    project_id: str | None = None,
) -> str:
    """Issue a short-lived (8 h) access token. jti makes each token unique."""
    payload: dict[str, Any] = {
        "sub": user_id,
        "role": role,
        "typ": "access",
        "jti": str(uuid.uuid4()),
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(hours=ACCESS_TOKEN_EXPIRY_HOURS),
    }
    if project_id:
        payload["project_id"] = project_id
    return _encode(payload)


def create_refresh_token(user_id: str) -> str:
    """Issue a long-lived (7 d) refresh token. jti makes each token unique."""
    payload: dict[str, Any] = {
        "sub": user_id,
        "typ": "refresh",
        "jti": str(uuid.uuid4()),
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(days=REFRESH_TOKEN_EXPIRY_DAYS),
    }
    return _encode(payload)


def verify_refresh_token(token: str) -> dict[str, Any]:
    """Decode and validate a refresh token. Raises HTTPException on failure."""
    payload = _decode(token)
    if payload.get("typ") != "refresh":
        raise HTTPException(status_code=401, detail="Not a refresh token")
    return payload


class UserRole(str, Enum):
    """Role hierarchy: VIEWER < OPERATOR < ADMIN."""

    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"

    def has_permission(self, required: "UserRole") -> bool:
        _order = [UserRole.VIEWER, UserRole.OPERATOR, UserRole.ADMIN]
        return _order.index(self) >= _order.index(required)


def create_token(user_id: str, role: str = UserRole.VIEWER.value, claims: dict[str, Any] | None = None) -> str:
    """Backward-compat alias — prefer create_access_token() for new callers."""
    payload: dict[str, Any] = {
        "sub": user_id,
        "role": role,
        "typ": "access",
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(hours=ACCESS_TOKEN_EXPIRY_HOURS),
        **(claims or {}),
    }
    return _encode(payload)


async def _is_token_revoked(jti: str | None) -> bool:
    if not jti:
        return False
    from infrastructure.metadata_db.session import AsyncSessionFactory
    from application.audit_service import AuditService

    async with AsyncSessionFactory() as session:
        return await AuditService(session).is_token_revoked(jti)


def verify_token(token: str) -> dict[str, Any]:
    """Verify and decode any platform JWT. Raises HTTPException on failure."""
    return _decode(token)


async def verify_token_async(token: str) -> dict[str, Any]:
    """Verify JWT and check the jti denylist."""
    payload = _decode(token)
    if await _is_token_revoked(payload.get("jti")):
        raise HTTPException(status_code=401, detail="Token has been revoked")
    return payload


def get_current_user(request: Request) -> dict[str, Any]:
    """FastAPI dependency — returns the decoded JWT payload from request state."""
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def require_role(minimum_role: UserRole) -> Any:
    """
    FastAPI dependency factory that enforces a minimum role level.

    Usage::

        @app.post("/admin-only")
        async def endpoint(_: dict = require_role(UserRole.ADMIN)):
            ...
    """

    def checker(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        role_str = user.get("role", UserRole.VIEWER.value)
        try:
            user_role = UserRole(role_str)
        except ValueError:
            user_role = UserRole.VIEWER
        if not user_role.has_permission(minimum_role):
            raise HTTPException(
                status_code=403,
                detail=f"Requires '{minimum_role.value}' role or higher",
            )
        return user

    return Depends(checker)


class AuthMiddleware(BaseHTTPMiddleware):
    """Middleware that protects all API routes except health and auth endpoints."""

    PUBLIC_PATHS = {
        "/health",
        "/health/deep",
        "/metrics",
        "/docs",
        "/openapi.json",
        # v1 auth paths
        "/api/v1/auth/login",
        "/api/v1/auth/token",
        "/api/v1/auth/refresh",
        "/api/v1/auth/dev-token",
        "/api/v1/auth/setup-required",
        "/api/v1/auth/setup",
        # Legacy flat paths (kept during deprecation window; redirected by middleware)
        "/auth/login",
        "/auth/token",
        "/auth/refresh",
    }

    async def dispatch(self, request: Request, call_next: Callable) -> Any:
        # Browsers send OPTIONS preflight without Authorization; CORS middleware answers it.
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        if path in self.PUBLIC_PATHS or path.startswith(("/docs", "/openapi.json", "/redoc")):
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(status_code=401, content={"detail": "Missing authorization header"})

        token = auth_header.split(" ", 1)[1]
        try:
            request.state.user = await verify_token_async(token)
        except HTTPException as e:
            return JSONResponse(status_code=e.status_code, content={"detail": e.detail})

        return await call_next(request)
