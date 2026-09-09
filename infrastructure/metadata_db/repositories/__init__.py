"""Repository classes for metadata DB access — one class per aggregate root.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from infrastructure.metadata_db.repositories.chunk_repository import ChunkRepository
from infrastructure.metadata_db.repositories.command_repository import CommandRepository
from infrastructure.metadata_db.repositories.connection_repository import ConnectionRepository
from infrastructure.metadata_db.repositories.job_repository import JobRepository
from infrastructure.metadata_db.repositories.project_repository import ProjectRepository
from infrastructure.metadata_db.repositories.user_repository import UserRepository
from infrastructure.metadata_db.repositories.replication_stream_repository import (
    ReplicationStreamRepository,
)
from infrastructure.metadata_db.repositories.notification_settings_repository import (
    NotificationSettingsRepository,
)
from infrastructure.metadata_db.repositories.migration_settings_repository import (
    MigrationSettingsRepository,
)
from infrastructure.metadata_db.repositories.replication_settings_repository import (
    ReplicationSettingsRepository,
)
from infrastructure.metadata_db.repositories.validation_repository import ValidationRepository

from infrastructure.metadata_db.repositories.transfer_job_repository import (
    TransferJobRepository,
)
from infrastructure.metadata_db.repositories.transfer_settings_repository import (
    TransferSettingsRepository,
)

__all__ = [
    "ChunkRepository",
    "CommandRepository",
    "ConnectionRepository",
    "JobRepository",
    "MigrationSettingsRepository",
    "NotificationSettingsRepository",
    "ProjectRepository",
    "ReplicationSettingsRepository",
    "ReplicationStreamRepository",
    "TransferJobRepository",
    "TransferSettingsRepository",
    "UserRepository",
    "ValidationRepository",
]
