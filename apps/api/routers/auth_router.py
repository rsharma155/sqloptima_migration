# Author: Ravi Sharma
# Copyright (c) 2026 Ravi Sharma
# SPDX-License-Identifier: MIT

"""Auth & user-management routes.

Public:  POST /auth/login, POST /auth/token, POST /auth/refresh
Admin:   GET/POST /users, GET/PUT/DELETE /users/{id}
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from application.audit_service import AuditService
from application.auth_service import AuthError, AuthService
from apps.api.rate_limit import available as _rate_limit_available
from apps.api.rate_limit import limiter as _limiter
from apps.api.middleware.auth import (
    UserRole,
    create_access_token,
    create_refresh_token,
    get_current_user,
    require_role,
    verify_refresh_token,
    create_token,
    verify_token,
)
from infrastructure.metadata_db.session import AsyncSessionFactory
from shared.security.audit_log import AuditAction

router = APIRouter(tags=["auth"])

_login_limit = (
    _limiter.limit("10/minute")
    if _rate_limit_available and _limiter is not None
    else lambda f: f
)


# ---- Models ----

class AuthRequest(BaseModel):
    username: str
    password: str


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class CreateUserRequest(BaseModel):
    username: str
    email: str
    password: str
    role: str = "viewer"


class UpdateRoleRequest(BaseModel):
    role: str


class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    role: str
    is_active: bool
    created_at: str
    last_login_at: str | None = None


# ---- Auth endpoints ----

@router.post("/auth/login", response_model=AuthResponse)
@_login_limit
async def login(request: Request, req: AuthRequest):
    source_ip = request.client.host if request.client else None
    async with AsyncSessionFactory() as sess:
        audit = AuditService(sess)
        try:
            user = await AuthService(sess).authenticate(req.username, req.password)
        except AuthError:
            await audit.record(
                AuditAction.USER_LOGIN,
                actor=req.username,
                resource="auth/login",
                source_ip=source_ip,
                success=False,
                error_message="Invalid credentials",
            )
            raise HTTPException(status_code=401, detail="Invalid credentials")
        access = create_access_token(user.id, user.role)
        refresh = create_refresh_token(user.id)
        await AuthService(sess).create_session(user.id, refresh)
        await audit.record(
            AuditAction.USER_LOGIN,
            actor=user.username,
            resource="auth/login",
            source_ip=source_ip,
            details={"user_id": user.id, "role": user.role},
        )
    return AuthResponse(access_token=access, refresh_token=refresh)


@router.post("/auth/token", response_model=AuthResponse)
@_login_limit
async def token_alias(request: Request, req: AuthRequest):
    """Alias for /auth/login kept for backward compatibility."""
    return await login(request, req)


@router.post("/auth/logout", status_code=204, response_model=None)
async def logout(request: Request, current_user: dict = get_current_user) -> None:
    """Revoke the current access token via jti denylist."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization header")
    token = auth_header.split(" ", 1)[1]
    payload = verify_token(token)
    jti = payload.get("jti")
    exp = payload.get("exp")
    if jti and exp:
        expires_at = datetime.fromtimestamp(exp, tz=UTC)
        async with AsyncSessionFactory() as sess:
            await AuditService(sess).revoke_access_token(jti, expires_at)
            await AuditService(sess).record(
                AuditAction.USER_LOGOUT,
                actor=current_user.get("sub", "unknown"),
                resource="auth/logout",
                source_ip=request.client.host if request.client else None,
            )


@router.get("/auth/dev-token")
async def dev_token():
    """Development-only: returns a fresh admin token without credentials.
    Disabled in production (ENVIRONMENT=production)."""
    import os
    if os.environ.get("ENVIRONMENT", "development") == "production":
        raise HTTPException(status_code=404, detail="Not found")
    token = create_token("dev-admin", UserRole.ADMIN.value)
    return {"access_token": token, "token_type": "bearer"}


@router.get("/auth/setup-required")
async def check_setup_required():
    """Returns whether first-time admin setup is still needed (no users in DB)."""
    async with AsyncSessionFactory() as sess:
        count = await AuthService(sess).user_count()
    return {"setup_required": count == 0}


@router.post("/auth/setup", response_model=UserResponse, status_code=201)
async def setup_first_admin(req: CreateUserRequest):
    """Create the first admin user during initial setup.

    Returns 409 if any users already exist — setup can only run once.
    The created user always receives the 'admin' role regardless of what is sent.
    """
    async with AsyncSessionFactory() as sess:
        svc = AuthService(sess)
        if await svc.user_count() > 0:
            raise HTTPException(
                status_code=409,
                detail="Setup already completed. Please log in.",
            )
        try:
            u = await svc.create_user(
                username=req.username,
                email=req.email,
                password=req.password,
                role="admin",
            )
        except AuthError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
    return UserResponse(
        id=u.auth_user_id, username=u.username, email=u.email, role=u.role,
        is_active=u.is_active, created_at=u.created_at.isoformat(),
    )


@router.post("/auth/refresh", response_model=AuthResponse)
async def refresh_tokens(req: RefreshRequest):
    try:
        verify_refresh_token(req.refresh_token)
    except HTTPException:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    async with AsyncSessionFactory() as sess:
        svc = AuthService(sess)
        user_record = await svc.validate_refresh_session(req.refresh_token)
        if not user_record or not user_record.is_active:
            raise HTTPException(status_code=401, detail="Session expired or user deactivated")
        await svc.revoke_session(req.refresh_token)
        access = create_access_token(user_record.auth_user_id, user_record.role)
        new_refresh = create_refresh_token(user_record.auth_user_id)
        await svc.create_session(user_record.auth_user_id, new_refresh)
    return AuthResponse(access_token=access, refresh_token=new_refresh)


# ---- User management (Admin only) ----

@router.get("/users", response_model=list[UserResponse])
async def list_users(_: dict = require_role(UserRole.ADMIN)):
    async with AsyncSessionFactory() as sess:
        users = await AuthService(sess).list_users()
    return [
        UserResponse(
            id=u.auth_user_id, username=u.username, email=u.email, role=u.role,
            is_active=u.is_active, created_at=u.created_at.isoformat(),
            last_login_at=u.last_login_at.isoformat() if u.last_login_at else None,
        )
        for u in users
    ]


@router.post("/users", response_model=UserResponse, status_code=201)
async def create_user(req: CreateUserRequest, _: dict = require_role(UserRole.ADMIN)):
    async with AsyncSessionFactory() as sess:
        try:
            u = await AuthService(sess).create_user(
                username=req.username, email=req.email,
                password=req.password, role=req.role,
            )
        except AuthError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
    return UserResponse(
        id=u.auth_user_id, username=u.username, email=u.email, role=u.role,
        is_active=u.is_active, created_at=u.created_at.isoformat(),
    )


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(user_id: str, _: dict = require_role(UserRole.ADMIN)):
    async with AsyncSessionFactory() as sess:
        u = await AuthService(sess).get_user_by_id(user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse(
        id=u.auth_user_id, username=u.username, email=u.email, role=u.role,
        is_active=u.is_active, created_at=u.created_at.isoformat(),
        last_login_at=u.last_login_at.isoformat() if u.last_login_at else None,
    )


@router.put("/users/{user_id}/role", response_model=UserResponse)
async def update_user_role(user_id: str, req: UpdateRoleRequest, _: dict = require_role(UserRole.ADMIN)):
    async with AsyncSessionFactory() as sess:
        try:
            u = await AuthService(sess).update_role(user_id, req.role)
        except AuthError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
    return UserResponse(
        id=u.auth_user_id, username=u.username, email=u.email, role=u.role,
        is_active=u.is_active, created_at=u.created_at.isoformat(),
    )


@router.delete("/users/{user_id}", status_code=204, response_model=None)
async def delete_user(user_id: str, current_user: dict = require_role(UserRole.ADMIN)) -> None:
    if current_user.get("sub") == user_id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    async with AsyncSessionFactory() as sess:
        deleted = await AuthService(sess).delete_user(user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="User not found")
