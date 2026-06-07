"""
Module: models.py
Purpose: Change data capture replication pipeline
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class UserRole(StrEnum):
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


class IMCommand(BaseModel):
    source: str
    chat_id: str
    user_id: str
    user_role: UserRole
    command: str
    args: dict[str, Any] = Field(default_factory=dict)
    raw_text: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class IMEvent(BaseModel):
    id: str
    provider: str
    chat_id: str
    message_id: str
    text: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class IMProviderConfig(BaseModel):
    provider_type: str
    api_key: str = ""
    allowed_chat_ids: list[str] = Field(default_factory=list)
    enabled: bool = True
