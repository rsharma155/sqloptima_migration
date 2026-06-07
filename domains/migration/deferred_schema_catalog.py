"""
Module: deferred_schema_catalog.py
Purpose: Domain catalog of schema objects deferred until after bulk data migration.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)

# SQL Server sys.indexes.type values that cannot be auto-migrated to PostgreSQL.
_UNSUPPORTED_INDEX_TYPES = frozenset({3, 4, 5, 6, 7})

_IDENTITY_SQL = """
SELECT
    c.name AS column_name,
    TYPE_NAME(c.user_type_id) AS type_name,
    CAST(ic.seed_value AS BIGINT) AS seed_value,
    CAST(ic.increment_value AS BIGINT) AS increment_value,
    CAST(ic.last_value AS BIGINT) AS last_value
FROM sys.identity_columns ic
JOIN sys.columns c
  ON ic.object_id = c.object_id AND ic.column_id = c.column_id
WHERE ic.object_id = OBJECT_ID(?)
ORDER BY c.column_id
"""

_INDEX_SQL = """
SELECT
    i.name AS index_name,
    CAST(i.is_unique AS BIT) AS is_unique,
    CAST(i.is_primary_key AS BIT) AS is_primary_key,
    CAST(CASE WHEN i.type = 1 THEN 1 ELSE 0 END AS BIT) AS is_clustered,
    i.type AS index_type,
    i.filter_definition,
    c.name AS column_name,
    CAST(ic.is_included_column AS BIT) AS is_included,
    ic.key_ordinal
FROM sys.indexes i
JOIN sys.index_columns ic
  ON ic.object_id = i.object_id AND ic.index_id = i.index_id
JOIN sys.columns c
  ON c.object_id = ic.object_id AND c.column_id = ic.column_id
WHERE i.object_id = OBJECT_ID(?)
  AND i.type > 0
ORDER BY i.name, ic.key_ordinal
"""

_FK_SQL = """
SELECT
    fk.name AS constraint_name,
    pc.name AS column_name,
    OBJECT_SCHEMA_NAME(fk.referenced_object_id) AS referenced_schema,
    OBJECT_NAME(fk.referenced_object_id) AS referenced_table,
    rc.name AS referenced_column,
    fk.delete_referential_action_desc AS on_delete,
    fk.update_referential_action_desc AS on_update,
    fk.is_disabled
FROM sys.foreign_keys fk
JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id
JOIN sys.columns pc
  ON pc.object_id = fkc.parent_object_id AND pc.column_id = fkc.parent_column_id
JOIN sys.columns rc
  ON rc.object_id = fkc.referenced_object_id AND rc.column_id = fkc.referenced_column_id
WHERE fk.parent_object_id = OBJECT_ID(?)
ORDER BY fk.name, fkc.constraint_column_id
"""

_CHECK_SQL = """
SELECT
    cc.name AS constraint_name,
    cc.definition AS check_definition,
    cc.is_disabled
FROM sys.check_constraints cc
WHERE cc.parent_object_id = OBJECT_ID(?)
ORDER BY cc.name
"""

_DEFAULT_SQL = """
SELECT
    c.name AS column_name,
    dc.definition AS default_definition
FROM sys.columns c
JOIN sys.default_constraints dc ON c.default_object_id = dc.object_id
WHERE c.object_id = OBJECT_ID(?)
ORDER BY c.column_id
"""

_TRIGGER_SQL = """
SELECT
    t.name AS trigger_name,
    CAST(OBJECTPROPERTY(t.object_id, 'ExecIsInsertTrigger') AS BIT) AS is_insert,
    CAST(OBJECTPROPERTY(t.object_id, 'ExecIsUpdateTrigger') AS BIT) AS is_update,
    CAST(OBJECTPROPERTY(t.object_id, 'ExecIsDeleteTrigger') AS BIT) AS is_delete,
    t.is_disabled,
    OBJECT_DEFINITION(t.object_id) AS definition
FROM sys.triggers t
WHERE t.parent_id = OBJECT_ID(?)
  AND t.is_ms_shipped = 0
ORDER BY t.name
"""


@dataclass
class DeferredIdentityColumn:
    column_name: str
    data_type: str
    seed_value: int = 1
    increment_value: int = 1
    last_value: int | None = None


@dataclass
class DeferredSecondaryIndex:
    index_name: str
    is_unique: bool = False
    is_clustered: bool = False
    is_primary_key: bool = False
    key_columns: list[str] = field(default_factory=list)
    include_columns: list[str] = field(default_factory=list)
    filter_definition: str | None = None
    unsupported_reason: str | None = None


@dataclass
class DeferredForeignKey:
    constraint_name: str
    columns: list[str] = field(default_factory=list)
    referenced_schema: str = "dbo"
    referenced_table: str = ""
    referenced_columns: list[str] = field(default_factory=list)
    on_delete: str = "NO_ACTION"
    on_update: str = "NO_ACTION"
    is_disabled: bool = False


@dataclass
class DeferredCheckConstraint:
    constraint_name: str
    check_definition: str
    is_disabled: bool = False


@dataclass
class DeferredColumnDefault:
    column_name: str
    default_definition: str


@dataclass
class DeferredTrigger:
    trigger_name: str
    event_type: str
    definition: str | None = None
    is_disabled: bool = False


@dataclass
class DeferredTableSchema:
    source_schema: str
    table_name: str
    target_schema: str
    identity_columns: list[DeferredIdentityColumn] = field(default_factory=list)
    secondary_indexes: list[DeferredSecondaryIndex] = field(default_factory=list)
    foreign_keys: list[DeferredForeignKey] = field(default_factory=list)
    check_constraints: list[DeferredCheckConstraint] = field(default_factory=list)
    column_defaults: list[DeferredColumnDefault] = field(default_factory=list)
    triggers: list[DeferredTrigger] = field(default_factory=list)


def catalog_to_dict(catalog: DeferredTableSchema) -> dict[str, Any]:
    return asdict(catalog)


def catalog_from_dict(data: dict[str, Any]) -> DeferredTableSchema:
    return DeferredTableSchema(
        source_schema=data["source_schema"],
        table_name=data["table_name"],
        target_schema=data["target_schema"],
        identity_columns=[
            DeferredIdentityColumn(**ic) for ic in data.get("identity_columns", [])
        ],
        secondary_indexes=[
            DeferredSecondaryIndex(**ix) for ix in data.get("secondary_indexes", [])
        ],
        foreign_keys=[DeferredForeignKey(**fk) for fk in data.get("foreign_keys", [])],
        check_constraints=[
            DeferredCheckConstraint(**cc) for cc in data.get("check_constraints", [])
        ],
        column_defaults=[
            DeferredColumnDefault(**d) for d in data.get("column_defaults", [])
        ],
        triggers=[DeferredTrigger(**t) for t in data.get("triggers", [])],
    )


def _unsupported_index_reason(index_type: int) -> str | None:
    if index_type == 3:
        return "xml_index"
    if index_type == 4:
        return "spatial_index"
    if index_type in (5, 6):
        return "columnstore"
    if index_type == 7:
        return "hash_index"
    return None


class DeferredSchemaCatalogBuilder:
    """Discover SQL Server objects that must be applied after bulk data load."""

    def __init__(self, connector: Any) -> None:
        self._connector = connector

    async def build_for_table(
        self,
        source_schema: str,
        table_name: str,
        target_schema: str,
    ) -> DeferredTableSchema:
        full_name = f"{source_schema}.{table_name}"
        catalog = DeferredTableSchema(
            source_schema=source_schema,
            table_name=table_name,
            target_schema=target_schema,
        )
        catalog.identity_columns = await self._discover_identities(full_name)
        catalog.secondary_indexes = await self._discover_indexes(full_name)
        catalog.foreign_keys = await self._discover_foreign_keys(full_name)
        catalog.check_constraints = await self._discover_checks(full_name)
        catalog.column_defaults = await self._discover_defaults(full_name)
        catalog.triggers = await self._discover_triggers(full_name)
        logger.info(
            "deferred_schema_catalog_built",
            table=full_name,
            identities=len(catalog.identity_columns),
            indexes=len(catalog.secondary_indexes),
            foreign_keys=len(catalog.foreign_keys),
            checks=len(catalog.check_constraints),
            defaults=len(catalog.column_defaults),
            triggers=len(catalog.triggers),
        )
        return catalog

    async def _discover_identities(self, full_name: str) -> list[DeferredIdentityColumn]:
        rows = await self._connector.execute(_IDENTITY_SQL, {"full_name": full_name})
        return [
            DeferredIdentityColumn(
                column_name=str(r["column_name"]),
                data_type=str(r["type_name"]),
                seed_value=int(r.get("seed_value") or 1),
                increment_value=int(r.get("increment_value") or 1),
                last_value=int(r["last_value"]) if r.get("last_value") is not None else None,
            )
            for r in rows
        ]

    async def _discover_indexes(self, full_name: str) -> list[DeferredSecondaryIndex]:
        rows = await self._connector.execute(_INDEX_SQL, {"full_name": full_name})
        index_map: dict[str, DeferredSecondaryIndex] = {}
        for row in rows:
            if bool(row.get("is_primary_key")):
                continue
            name = str(row["index_name"])
            if name not in index_map:
                index_type = int(row.get("index_type") or 2)
                index_map[name] = DeferredSecondaryIndex(
                    index_name=name,
                    is_unique=bool(row.get("is_unique")),
                    is_clustered=bool(row.get("is_clustered")),
                    is_primary_key=False,
                    filter_definition=row.get("filter_definition"),
                    unsupported_reason=_unsupported_index_reason(index_type),
                )
            idx = index_map[name]
            col = str(row["column_name"])
            if bool(row.get("is_included")):
                idx.include_columns.append(col)
            else:
                idx.key_columns.append(col)
        return list(index_map.values())

    async def _discover_foreign_keys(self, full_name: str) -> list[DeferredForeignKey]:
        rows = await self._connector.execute(_FK_SQL, {"full_name": full_name})
        fk_map: dict[str, DeferredForeignKey] = {}
        for row in rows:
            name = str(row["constraint_name"])
            if name not in fk_map:
                fk_map[name] = DeferredForeignKey(
                    constraint_name=name,
                    referenced_schema=str(row.get("referenced_schema") or "dbo"),
                    referenced_table=str(row.get("referenced_table") or ""),
                    on_delete=str(row.get("on_delete") or "NO_ACTION"),
                    on_update=str(row.get("on_update") or "NO_ACTION"),
                    is_disabled=bool(row.get("is_disabled")),
                )
            fk = fk_map[name]
            fk.columns.append(str(row["column_name"]))
            fk.referenced_columns.append(str(row["referenced_column"]))
        return list(fk_map.values())

    async def _discover_checks(self, full_name: str) -> list[DeferredCheckConstraint]:
        rows = await self._connector.execute(_CHECK_SQL, {"full_name": full_name})
        return [
            DeferredCheckConstraint(
                constraint_name=str(r["constraint_name"]),
                check_definition=str(r["check_definition"]),
                is_disabled=bool(r.get("is_disabled")),
            )
            for r in rows
        ]

    async def _discover_defaults(self, full_name: str) -> list[DeferredColumnDefault]:
        rows = await self._connector.execute(_DEFAULT_SQL, {"full_name": full_name})
        return [
            DeferredColumnDefault(
                column_name=str(r["column_name"]),
                default_definition=str(r["default_definition"]),
            )
            for r in rows
        ]

    async def _discover_triggers(self, full_name: str) -> list[DeferredTrigger]:
        rows = await self._connector.execute(_TRIGGER_SQL, {"full_name": full_name})
        triggers: list[DeferredTrigger] = []
        for row in rows:
            event = "INSERT" if row.get("is_insert") else None
            if row.get("is_update"):
                event = "UPDATE"
            elif row.get("is_delete"):
                event = "DELETE"
            triggers.append(
                DeferredTrigger(
                    trigger_name=str(row["trigger_name"]),
                    event_type=event or "UNKNOWN",
                    definition=row.get("definition"),
                    is_disabled=bool(row.get("is_disabled")),
                )
            )
        return triggers
