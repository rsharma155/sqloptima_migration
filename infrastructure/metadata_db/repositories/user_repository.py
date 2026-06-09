"""Repository for auth_users and auth_sessions.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.metadata_db.models import SessionRecord, UserRecord


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------

    async def get_all(self) -> list[UserRecord]:
        result = await self._session.execute(select(UserRecord).order_by(UserRecord.created_at))
        return list(result.scalars().all())

    async def get_by_id(self, user_id: str) -> UserRecord | None:
        result = await self._session.execute(
            select(UserRecord).where(UserRecord.auth_user_id == user_id.strip())
        )
        return result.scalar_one_or_none()

    async def get_by_username(self, username: str) -> UserRecord | None:
        normalized = username.strip().lower()
        result = await self._session.execute(
            select(UserRecord).where(func.lower(UserRecord.username) == normalized)
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> UserRecord | None:
        result = await self._session.execute(
            select(UserRecord).where(UserRecord.email == email)
        )
        return result.scalar_one_or_none()

    async def count(self) -> int:
        result = await self._session.execute(select(UserRecord))
        return len(result.scalars().all())

    async def create(self, record: UserRecord) -> UserRecord:
        self._session.add(record)
        await self._session.commit()
        await self._session.refresh(record)
        return record

    async def update(self, record: UserRecord) -> UserRecord:
        merged = await self._session.merge(record)
        await self._session.commit()
        return merged

    async def delete(self, user_id: str) -> bool:
        normalized_id = user_id.strip()
        record = await self.get_by_id(normalized_id)
        if not record:
            return False
        # Remove refresh-token sessions first (SQLite FK enforcement varies).
        await self._session.execute(
            delete(SessionRecord).where(SessionRecord.auth_user_id == normalized_id)
        )
        await self._session.delete(record)
        await self._session.commit()
        return True

    async def record_login(self, user_id: str) -> None:
        record = await self.get_by_id(user_id)
        if record:
            record.last_login_at = datetime.now(UTC)
            await self._session.commit()

    # ------------------------------------------------------------------
    # Sessions (refresh tokens)
    # ------------------------------------------------------------------

    @staticmethod
    def _hash_token(raw_token: str) -> str:
        return hashlib.sha256(raw_token.encode()).hexdigest()

    async def create_session(self, session_record: SessionRecord) -> SessionRecord:
        self._session.add(session_record)
        await self._session.commit()
        await self._session.refresh(session_record)
        return session_record

    async def get_session_by_token(self, raw_token: str) -> SessionRecord | None:
        token_hash = self._hash_token(raw_token)
        result = await self._session.execute(
            select(SessionRecord).where(SessionRecord.refresh_token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def delete_session(self, session_id: str) -> None:
        record = await self._session.get(SessionRecord, session_id)
        if record:
            await self._session.delete(record)
            await self._session.commit()

    async def delete_expired_sessions(self) -> int:
        result = await self._session.execute(
            select(SessionRecord).where(SessionRecord.expires_at < datetime.now(UTC))
        )
        expired = list(result.scalars().all())
        for s in expired:
            await self._session.delete(s)
        await self._session.commit()
        return len(expired)
