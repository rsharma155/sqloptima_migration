"""
Module: base_connector.py
Purpose: Abstract port interfaces for database connectors (Hexagonal Architecture)
Author: Migration Platform Team
Created: 2026-05-22
Domain: Contracts
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from shared.contracts.config_validation import validate_port
from shared.kernel.database_object import DatabaseObject, Table


class ConnectionConfig:
    """Configuration for database connections."""

    def __init__(
        self,
        host: str,
        port: int,
        database: str,
        username: str,
        password: str,
        schema: str | None = None,
        extra_params: dict[str, str] | None = None,
    ):
        validate_port(port)
        self.host = host
        self.port = port
        self.database = database
        self.username = username
        self.password = password
        self.schema = schema
        self.extra_params = extra_params or {}

    @property
    def connection_string(self) -> str:
        """Subclasses should override to provide driver-specific connection string."""
        raise NotImplementedError


class DatabaseConnector(ABC):
    """Abstract port for database connectivity."""

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the database."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Close the database connection."""

    @abstractmethod
    async def execute(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Execute a query and return results as list of dicts."""

    @abstractmethod
    async def execute_many(self, query: str, params_list: list[dict[str, Any]]) -> None:
        """Execute a query with multiple parameter sets."""


class MetadataDiscoveryPort(ABC):
    """Abstract port for database metadata discovery."""

    @abstractmethod
    async def discover_databases(self) -> list[DatabaseObject]:
        """Discover all databases on the server."""

    @abstractmethod
    async def discover_schemas(self, database: str) -> list[DatabaseObject]:
        """Discover all schemas in a database."""

    @abstractmethod
    async def discover_tables(self, database: str, schema: str) -> list[Table]:
        """Discover all tables with their columns in a schema."""

    @abstractmethod
    async def discover_views(self, database: str, schema: str) -> list[DatabaseObject]:
        """Discover all views in a schema."""

    @abstractmethod
    async def discover_procedures(self, database: str, schema: str) -> list[DatabaseObject]:
        """Discover all stored procedures in a schema."""

    @abstractmethod
    async def discover_functions(self, database: str, schema: str) -> list[DatabaseObject]:
        """Discover all functions in a schema."""

    @abstractmethod
    async def discover_indexes(self, database: str, schema: str, table: str) -> list[DatabaseObject]:
        """Discover all indexes for a table."""

    @abstractmethod
    async def discover_foreign_keys(self, database: str, schema: str, table: str) -> list[DatabaseObject]:
        """Discover all foreign keys for a table."""

    @abstractmethod
    async def discover_dependencies(self, database: str) -> list[dict[str, Any]]:
        """Discover object dependencies (for lineage graph)."""

    @abstractmethod
    async def get_schema_ddl(self, database: str, schema: str) -> dict[str, str]:
        """Get DDL definitions for all objects in a schema."""


class DataMigrationPort(ABC):
    """Abstract port for data movement operations."""

    @abstractmethod
    async def extract_chunk(self, query: str, offset: int, limit: int) -> AsyncIterator[list[dict[str, Any]]]:
        """Extract a chunk of data from source."""

    @abstractmethod
    async def load_chunk(self, table: str, columns: list[str], rows: list[tuple]) -> int:
        """Load a chunk of data into target. Returns row count."""

    @abstractmethod
    async def validate_row_count(self, table: str) -> tuple[int, int]:
        """Validate row counts between source and target. Returns (source_count, target_count)."""
