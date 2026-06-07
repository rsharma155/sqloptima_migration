"""AuthService — user lifecycle, credential verification, and session management.

Responsibilities:
- Hash passwords with bcrypt on create/change.
- Verify credentials with timing-safe bcrypt compare.
- Bootstrap the first admin user from env var on first startup.
- Manage DB-backed refresh token sessions.

This layer knows nothing about HTTP or JWT encoding — those stay in middleware/auth.py.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import bcrypt
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.metadata_db.models import SessionRecord, UserRecord
from infrastructure.metadata_db.repositories.user_repository import UserRepository
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)

# Pre-computed dummy hash used when the username is not found.
# Ensures bcrypt always runs so response time doesn't leak user existence.
_DUMMY_HASH = bcrypt.hashpw(b"dummy-timing-guard", bcrypt.gensalt(rounds=12)).decode()

REFRESH_TOKEN_TTL_DAYS = 7


@dataclass(frozen=True)
class AuthenticatedUser:
    id: str
    username: str
    email: str
    role: str
    is_active: bool


class AuthError(Exception):
    """Raised by AuthService for credential/permission failures."""


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = UserRepository(session)

    # ------------------------------------------------------------------
    # Password helpers
    # ------------------------------------------------------------------

    @staticmethod
    def hash_password(plaintext: str) -> str:
        return bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt(rounds=12)).decode()

    @staticmethod
    def verify_password(plaintext: str, hashed: str) -> bool:
        try:
            return bcrypt.checkpw(plaintext.encode(), hashed.encode())
        except Exception:
            return False

    # ------------------------------------------------------------------
    # User CRUD
    # ------------------------------------------------------------------

    async def create_user(
        self,
        username: str,
        email: str,
        password: str,
        role: str = "viewer",
    ) -> UserRecord:
        if await self._repo.get_by_username(username):
            raise AuthError(f"Username '{username}' is already taken")
        if await self._repo.get_by_email(email):
            raise AuthError(f"Email '{email}' is already registered")
        record = UserRecord(
            auth_user_id=str(uuid4()),
            username=username,
            email=email,
            password_hash=self.hash_password(password),
            role=role,
            is_active=True,
            created_at=datetime.now(UTC),
        )
        return await self._repo.create(record)

    async def get_user_by_id(self, user_id: str) -> UserRecord | None:
        return await self._repo.get_by_id(user_id)

    async def list_users(self) -> list[UserRecord]:
        return await self._repo.get_all()

    async def update_role(self, user_id: str, new_role: str) -> UserRecord:
        record = await self._repo.get_by_id(user_id)
        if not record:
            raise AuthError(f"User '{user_id}' not found")
        record.role = new_role
        return await self._repo.update(record)

    async def deactivate_user(self, user_id: str) -> None:
        record = await self._repo.get_by_id(user_id)
        if not record:
            raise AuthError(f"User '{user_id}' not found")
        record.is_active = False
        await self._repo.update(record)

    async def user_count(self) -> int:
        return await self._repo.count()

    async def delete_user(self, user_id: str) -> bool:
        return await self._repo.delete(user_id)

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    async def authenticate(self, username: str, password: str) -> AuthenticatedUser:
        """Verify credentials and return the authenticated user.

        Raises AuthError on invalid credentials or inactive account.
        """
        record = await self._repo.get_by_username(username)
        # Always run bcrypt even when user is not found to prevent timing attacks.
        stored = record.password_hash if record else _DUMMY_HASH
        if not self.verify_password(password, stored) or not record:
            raise AuthError("Invalid username or password")
        if not record.is_active:
            raise AuthError("Account is deactivated")
        await self._repo.record_login(record.auth_user_id)
        return AuthenticatedUser(
            id=record.auth_user_id,
            username=record.username,
            email=record.email,
            role=record.role,
            is_active=record.is_active,
        )

    # ------------------------------------------------------------------
    # Refresh token sessions
    # ------------------------------------------------------------------

    async def create_session(self, user_id: str, raw_refresh_token: str) -> SessionRecord:
        token_hash = hashlib.sha256(raw_refresh_token.encode()).hexdigest()
        session_record = SessionRecord(
            auth_session_id=str(uuid4()),
            auth_user_id=user_id,
            refresh_token_hash=token_hash,
            expires_at=datetime.now(UTC) + timedelta(days=REFRESH_TOKEN_TTL_DAYS),
            created_at=datetime.now(UTC),
        )
        return await self._repo.create_session(session_record)

    async def validate_refresh_session(self, raw_refresh_token: str) -> UserRecord | None:
        """Return the user linked to a valid (non-expired) refresh token."""
        session = await self._repo.get_session_by_token(raw_refresh_token)
        if not session:
            return None
        # SQLite returns naive datetimes; normalise to UTC before comparing.
        expires = session.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        if expires < datetime.now(UTC):
            await self._repo.delete_session(session.auth_session_id)
            return None
        return await self._repo.get_by_id(session.auth_user_id)

    async def revoke_session(self, raw_refresh_token: str) -> None:
        session = await self._repo.get_session_by_token(raw_refresh_token)
        if session:
            await self._repo.delete_session(session.auth_session_id)

    # ------------------------------------------------------------------
    # Bootstrap
    # ------------------------------------------------------------------

    async def bootstrap_admin(self) -> None:
        """Create the first admin user from the environment if no users exist.

        Only runs when MIGRATION_ADMIN_PASSWORD is set and the user table is
        empty, so it is safe to call on every startup.
        """
        password = os.environ.get("MIGRATION_ADMIN_PASSWORD")
        if not password:
            return
        if await self._repo.count() > 0:
            return
        await self.create_user(
            username="admin",
            email="admin@localhost",
            password=password,
            role="admin",
        )
        logger.info("bootstrap_admin_created", username="admin")

