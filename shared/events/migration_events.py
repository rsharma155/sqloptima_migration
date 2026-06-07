"""
Module: migration_events.py
Purpose: Domain event definitions for event-driven orchestration
Author: Migration Platform Team
Created: 2026-05-22
Domain: Shared Events
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class EventPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DomainEvent(BaseModel):
    """Base class for all domain events."""

    event_id: UUID = Field(default_factory=uuid4)
    event_type: str
    correlation_id: UUID | None = None
    causation_id: UUID | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    priority: EventPriority = EventPriority.MEDIUM
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DiscoveryStarted(DomainEvent):
    event_type: str = "discovery.started"


class DiscoveryCompleted(DomainEvent):
    event_type: str = "discovery.completed"


class DiscoveryFailed(DomainEvent):
    event_type: str = "discovery.failed"


class ConversionStarted(DomainEvent):
    event_type: str = "conversion.started"


class ConversionCompleted(DomainEvent):
    event_type: str = "conversion.completed"


class ConversionFailed(DomainEvent):
    event_type: str = "conversion.failed"


class MigrationStarted(DomainEvent):
    event_type: str = "migration.started"


class MigrationProgress(DomainEvent):
    event_type: str = "migration.progress"


class MigrationCompleted(DomainEvent):
    event_type: str = "migration.completed"


class MigrationFailed(DomainEvent):
    event_type: str = "migration.failed"


class ValidationCompleted(DomainEvent):
    event_type: str = "validation.completed"


class ValidationFailed(DomainEvent):
    event_type: str = "validation.failed"
