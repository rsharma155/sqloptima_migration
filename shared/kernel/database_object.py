"""
Module: database_object.py
Purpose: Domain models for database objects (tables, columns, procedures, etc.)
Author: Migration Platform Team
Created: 2026-05-22
Domain: Shared Kernel
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import Field

from shared.kernel.base_entity import DomainEntity, ValueObject


class DatabaseObjectType(StrEnum):
    DATABASE = "database"
    SCHEMA = "schema"
    TABLE = "table"
    VIEW = "view"
    MATERIALIZED_VIEW = "materialized_view"
    COLUMN = "column"
    PRIMARY_KEY = "primary_key"
    FOREIGN_KEY = "foreign_key"
    INDEX = "index"
    CONSTRAINT = "constraint"
    DEFAULT = "default"
    SEQUENCE = "sequence"
    SYNONYM = "synonym"
    TRIGGER = "trigger"
    PROCEDURE = "procedure"
    FUNCTION = "function"
    TABLE_TYPE = "table_type"
    PARTITION_SCHEME = "partition_scheme"
    USER_DEFINED_TYPE = "user_defined_type"
    XML_SCHEMA = "xml_schema"


class CompatibilityStatus(StrEnum):
    AUTO_CONVERTIBLE = "auto_convertible"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"
    RISKY = "risky"
    PERFORMANCE_RISK = "performance_risk"


class DataType(ValueObject):
    """Represents a data type with type name, precision, scale, and nullable."""

    type_name: str
    precision: int | None = None
    scale: int | None = None
    max_length: int | None = None
    is_nullable: bool = True
    is_user_defined: bool = False
    udt_name: str | None = None
    schema_name: str | None = None


class DatabaseObject(DomainEntity):
    """Base class for all database objects discovered from source."""

    object_type: DatabaseObjectType
    database_name: str
    schema_name: str
    object_name: str
    fully_qualified_name: str = ""
    source_definition: str | None = None
    compatibility_status: CompatibilityStatus = CompatibilityStatus.AUTO_CONVERTIBLE
    compatibility_notes: list[str] = Field(default_factory=list)
    properties: dict[str, Any] = Field(default_factory=dict)

    def __init__(self, **data):
        super().__init__(**data)
        if not self.fully_qualified_name:
            self.fully_qualified_name = f"{self.database_name}.{self.schema_name}.{self.object_name}"


class Column(DomainEntity):
    """Represents a table/view column with data type and constraints."""

    table_id: UUID | None = None
    column_name: str
    ordinal_position: int
    data_type: DataType
    is_identity: bool = False
    is_computed: bool = False
    computed_definition: str | None = None
    default_value: str | None = None
    is_nullable: bool = True
    collation_name: str | None = None
    description: str | None = None


class Table(DatabaseObject):
    """Represents a database table with columns, constraints, and indexes."""

    columns: list[Column] = Field(default_factory=list)
    is_temporal: bool = False
    is_memory_optimized: bool = False
    partition_scheme: str | None = None
    row_count_estimate: int | None = None
    data_size_bytes: int | None = None
    index_count: int = 0

    def __init__(self, **data):
        data["object_type"] = DatabaseObjectType.TABLE
        super().__init__(**data)
