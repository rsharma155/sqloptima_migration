"""
Module: base_entity.py
Purpose: Base domain entity with identity, equality, and audit fields
Author: Migration Platform Team
Created: 2026-05-22
Domain: Shared Kernel
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class DomainEntity(BaseModel):
    """Base class for all domain entities with identity and audit fields."""

    model_config = ConfigDict(validate_assignment=True)

    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    version: int = Field(default=1, ge=1)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, DomainEntity):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)


class ValueObject(BaseModel):
    """Base class for immutable value objects."""

    model_config = ConfigDict(frozen=True)
