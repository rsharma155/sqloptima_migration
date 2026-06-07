"""Unit tests for AuthService — user lifecycle, authentication, and sessions.

Uses an in-memory SQLite DB per test. No HTTP layer involved.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("METADATA_DB_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("MIGRATION_JWT_SECRET", "test-jwt-secret-for-unit-tests-only")
os.environ.setdefault("MIGRATION_MASTER_KEY", "test-master-key-for-unit-tests-only")

from application.auth_service import AuthError, AuthService
from infrastructure.metadata_db.models import Base, SessionRecord


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as sess:
        yield sess
    await engine.dispose()


@pytest.fixture
async def svc(session: AsyncSession) -> AuthService:
    return AuthService(session)


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

class TestPasswordHashing:
    def test_hash_is_not_plaintext(self):
        hashed = AuthService.hash_password("secret")
        assert hashed != "secret"

    def test_verify_correct_password(self):
        hashed = AuthService.hash_password("correct")
        assert AuthService.verify_password("correct", hashed) is True

    def test_reject_wrong_password(self):
        hashed = AuthService.hash_password("correct")
        assert AuthService.verify_password("wrong", hashed) is False

    def test_two_hashes_of_same_password_differ(self):
        h1 = AuthService.hash_password("same")
        h2 = AuthService.hash_password("same")
        assert h1 != h2


# ---------------------------------------------------------------------------
# User CRUD
# ---------------------------------------------------------------------------

class TestUserCrud:
    async def test_create_user_succeeds(self, svc: AuthService):
        user = await svc.create_user("alice", "alice@example.com", "pass1", "viewer")
        assert user.username == "alice"
        assert user.email == "alice@example.com"
        assert user.role == "viewer"
        assert user.is_active is True
        assert user.password_hash != "pass1"

    async def test_duplicate_username_raises(self, svc: AuthService):
        await svc.create_user("bob", "bob@example.com", "pw")
        with pytest.raises(AuthError, match="already taken"):
            await svc.create_user("bob", "other@example.com", "pw")

    async def test_duplicate_email_raises(self, svc: AuthService):
        await svc.create_user("carol", "carol@example.com", "pw")
        with pytest.raises(AuthError, match="already registered"):
            await svc.create_user("carol2", "carol@example.com", "pw")

    async def test_get_user_by_id(self, svc: AuthService):
        user = await svc.create_user("dave", "dave@example.com", "pw")
        fetched = await svc.get_user_by_id(user.auth_user_id)
        assert fetched is not None
        assert fetched.username == "dave"

    async def test_get_nonexistent_user_returns_none(self, svc: AuthService):
        assert await svc.get_user_by_id("00000000-0000-0000-0000-000000000000") is None

    async def test_list_users_returns_all(self, svc: AuthService):
        await svc.create_user("u1", "u1@e.com", "pw")
        await svc.create_user("u2", "u2@e.com", "pw")
        users = await svc.list_users()
        assert len(users) == 2

    async def test_update_role(self, svc: AuthService):
        user = await svc.create_user("eve", "eve@example.com", "pw", "viewer")
        updated = await svc.update_role(user.auth_user_id, "operator")
        assert updated.role == "operator"

    async def test_update_role_unknown_user_raises(self, svc: AuthService):
        with pytest.raises(AuthError, match="not found"):
            await svc.update_role("nonexistent", "admin")

    async def test_delete_user(self, svc: AuthService):
        user = await svc.create_user("frank", "frank@example.com", "pw")
        assert await svc.delete_user(user.auth_user_id) is True
        assert await svc.get_user_by_id(user.auth_user_id) is None

    async def test_delete_nonexistent_returns_false(self, svc: AuthService):
        assert await svc.delete_user("nonexistent") is False


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

class TestAuthentication:
    async def test_valid_credentials_succeed(self, svc: AuthService):
        await svc.create_user("grace", "grace@example.com", "correctpw", "operator")
        user = await svc.authenticate("grace", "correctpw")
        assert user.username == "grace"
        assert user.role == "operator"

    async def test_wrong_password_raises(self, svc: AuthService):
        await svc.create_user("hank", "hank@example.com", "rightpw")
        with pytest.raises(AuthError, match="Invalid"):
            await svc.authenticate("hank", "wrongpw")

    async def test_unknown_username_raises(self, svc: AuthService):
        with pytest.raises(AuthError, match="Invalid"):
            await svc.authenticate("nobody", "anything")

    async def test_inactive_user_raises(self, svc: AuthService):
        user = await svc.create_user("iris", "iris@example.com", "pw")
        await svc.deactivate_user(user.auth_user_id)
        with pytest.raises(AuthError, match="deactivated"):
            await svc.authenticate("iris", "pw")

    async def test_successful_login_records_last_login(self, svc: AuthService):
        user = await svc.create_user("jack", "jack@example.com", "pw")
        assert user.last_login_at is None
        await svc.authenticate("jack", "pw")
        updated = await svc.get_user_by_id(user.auth_user_id)
        assert updated is not None
        assert updated.last_login_at is not None

    async def test_timing_safe_against_missing_user(self, svc: AuthService):
        """Ensure authenticate() doesn't short-circuit before bcrypt on missing user."""
        import time
        t0 = time.monotonic()
        try:
            await svc.authenticate("ghost", "anything")
        except AuthError:
            pass
        elapsed = time.monotonic() - t0
        # bcrypt should take > 50ms — confirms we didn't fast-fail on missing user
        assert elapsed > 0.05, "authenticate() should run bcrypt even when user is missing"


# ---------------------------------------------------------------------------
# Session management (refresh tokens)
# ---------------------------------------------------------------------------

class TestSessionManagement:
    async def test_create_and_validate_session(self, svc: AuthService):
        user = await svc.create_user("kim", "kim@example.com", "pw")
        raw_token = "raw-refresh-token-abc123"
        await svc.create_session(user.auth_user_id, raw_token)
        found = await svc.validate_refresh_session(raw_token)
        assert found is not None
        assert found.auth_user_id == user.auth_user_id

    async def test_invalid_token_returns_none(self, svc: AuthService):
        assert await svc.validate_refresh_session("not-a-real-token") is None

    async def test_revoke_session(self, svc: AuthService):
        user = await svc.create_user("leo", "leo@example.com", "pw")
        token = "revoke-me-token"
        await svc.create_session(user.auth_user_id, token)
        await svc.revoke_session(token)
        assert await svc.validate_refresh_session(token) is None

    async def test_expired_session_returns_none(self, session: AsyncSession, svc: AuthService):
        user = await svc.create_user("mia", "mia@example.com", "pw")
        token = "expired-token"
        token_hash = __import__("hashlib").sha256(token.encode()).hexdigest()
        expired_session = SessionRecord(
            auth_session_id=__import__("uuid").uuid4().hex,
            auth_user_id=user.auth_user_id,
            refresh_token_hash=token_hash,
            expires_at=datetime.now(UTC) - timedelta(hours=1),
            created_at=datetime.now(UTC) - timedelta(days=8),
        )
        session.add(expired_session)
        await session.commit()
        assert await svc.validate_refresh_session(token) is None


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

class TestBootstrap:
    async def test_bootstrap_creates_admin_when_empty(self, svc: AuthService, monkeypatch):
        monkeypatch.setenv("MIGRATION_ADMIN_PASSWORD", "bootstrap-pass")
        await svc.bootstrap_admin()
        users = await svc.list_users()
        assert len(users) == 1
        assert users[0].username == "admin"
        assert users[0].role == "admin"

    async def test_bootstrap_noop_when_users_exist(self, svc: AuthService, monkeypatch):
        monkeypatch.setenv("MIGRATION_ADMIN_PASSWORD", "bootstrap-pass")
        await svc.create_user("existing", "e@e.com", "pw")
        await svc.bootstrap_admin()
        users = await svc.list_users()
        # Only the pre-existing user — bootstrap did not run
        assert len(users) == 1
        assert users[0].username == "existing"

    async def test_bootstrap_noop_without_env_var(self, svc: AuthService, monkeypatch):
        monkeypatch.delenv("MIGRATION_ADMIN_PASSWORD", raising=False)
        await svc.bootstrap_admin()
        assert await svc.list_users() == []
