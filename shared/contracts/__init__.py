"""Abstract port interfaces for database connectors (Hexagonal Architecture).
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from shared.contracts.base_connector import ConnectionConfig, DatabaseConnector, DataMigrationPort, MetadataDiscoveryPort

__all__ = ["ConnectionConfig", "DatabaseConnector", "DataMigrationPort", "MetadataDiscoveryPort"]
