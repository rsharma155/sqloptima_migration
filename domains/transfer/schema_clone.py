"""
Module: schema_clone.py
Purpose: Homogeneous Transfer DDL — T-SQL as-is (SQL Server) and native CREATE TABLE (Postgres).
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from domains.transfer.transfer_path import TransferPath

ClonePhase = Literal["pre_copy", "post_copy"]
CloneKind = Literal[
    "schema",
    "table",
    "index",
    "foreign_key",
    "check",
    "trigger",
    "view",
    "procedure",
    "function",
]

_CHAR_TYPES = frozenset({"char", "varchar", "nchar", "nvarchar", "binary", "varbinary"})
_DECIMAL_TYPES = frozenset({"decimal", "numeric"})
_SCALE_TYPES = frozenset({"datetime2", "time", "datetimeoffset"})


@dataclass(frozen=True, slots=True)
class SchemaCloneStatement:
    phase: ClonePhase
    kind: CloneKind
    sql: str
    schema: str = ""
    name: str = ""
    skip_if_exists: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "kind": self.kind,
            "sql": self.sql,
            "schema": self.schema,
            "name": self.name,
            "skip_if_exists": self.skip_if_exists,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SchemaCloneStatement:
        return cls(
            phase=str(data["phase"]),  # type: ignore[arg-type]
            kind=str(data["kind"]),  # type: ignore[arg-type]
            sql=str(data["sql"]),
            schema=str(data.get("schema") or ""),
            name=str(data.get("name") or ""),
            skip_if_exists=bool(data.get("skip_if_exists", True)),
        )


@dataclass(frozen=True, slots=True)
class SchemaClonePlan:
    create_if_missing: bool = False
    clone_objects: bool = False
    statements: tuple[SchemaCloneStatement, ...] = ()
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "create_if_missing": self.create_if_missing,
            "clone_objects": self.clone_objects,
            "statements": [s.to_dict() for s in self.statements],
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SchemaClonePlan:
        if not data:
            return cls()
        stmts = tuple(SchemaCloneStatement.from_dict(s) for s in (data.get("statements") or []))
        return cls(
            create_if_missing=bool(data.get("create_if_missing")),
            clone_objects=bool(data.get("clone_objects")),
            statements=stmts,
            notes=tuple(str(n) for n in (data.get("notes") or ())),
        )

    def pre_copy(self) -> tuple[SchemaCloneStatement, ...]:
        return tuple(s for s in self.statements if s.phase == "pre_copy")

    def post_copy(self) -> tuple[SchemaCloneStatement, ...]:
        return tuple(s for s in self.statements if s.phase == "post_copy")


def quote_mssql_ident(ident: str) -> str:
    return "[" + str(ident).replace("]", "]]") + "]"


def quoted_mssql_table(schema: str, table: str) -> str:
    return f"{quote_mssql_ident(schema)}.{quote_mssql_ident(table)}"


def quote_pg_ident_local(ident: str) -> str:
    return '"' + str(ident).replace('"', '""') + '"'


def supports_tsql_object_clone(path: TransferPath) -> bool:
    return path is TransferPath.MSSQL_TO_MSSQL


def supports_table_clone(path: TransferPath) -> bool:
    return path in {
        TransferPath.MSSQL_TO_MSSQL,
        TransferPath.PG_TO_PG,
        TransferPath.MSSQL_TO_PG,
    }


def format_mssql_type(
    type_name: str,
    *,
    max_length: int | None = None,
    precision: int | None = None,
    scale: int | None = None,
) -> str:
    raw = (type_name or "").strip()
    lower = raw.lower()
    if lower in _CHAR_TYPES:
        if max_length is None:
            return raw
        if int(max_length) < 0:
            return f"{raw}(max)"
        length = int(max_length)
        if lower in {"nchar", "nvarchar"}:
            length = length // 2 if length > 1 else length
        return f"{raw}({length})"
    if lower in _DECIMAL_TYPES and precision is not None:
        if scale is None:
            return f"{raw}({int(precision)})"
        return f"{raw}({int(precision)},{int(scale)})"
    if lower in _SCALE_TYPES and scale is not None:
        return f"{raw}({int(scale)})"
    if lower == "float" and precision is not None:
        return f"{raw}({int(precision)})"
    return raw or "nvarchar(max)"


def split_tsql_batches(definition: str) -> list[str]:
    """Split client-only GO batches; GO is not a T-SQL keyword."""
    batches: list[str] = []
    current: list[str] = []
    for line in (definition or "").splitlines():
        if line.strip().upper() == "GO":
            joined = "\n".join(current).strip()
            if joined:
                batches.append(joined)
            current = []
            continue
        current.append(line)
    joined = "\n".join(current).strip()
    if joined:
        batches.append(joined)
    return batches


def build_create_schema_tsql(schema: str) -> str:
    ident = quote_mssql_ident(schema)
    literal = schema.replace("'", "''")
    return (
        f"IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = N'{literal}')\n"
        f"    EXEC(N'CREATE SCHEMA {ident}')"
    )


def build_create_table_tsql(
    *,
    schema: str,
    table: str,
    columns: list[dict[str, Any]],
    primary_key_columns: list[str] | None = None,
    primary_key_name: str | None = None,
) -> str:
    if not columns:
        raise ValueError(f"No columns to clone for {schema}.{table}")
    lines: list[str] = []
    for col in columns:
        lines.append("    " + _mssql_column_line(col))
    pk_cols = [c for c in (primary_key_columns or []) if c]
    if pk_cols:
        pk_sql = ", ".join(quote_mssql_ident(c) for c in pk_cols)
        if primary_key_name:
            lines.append(
                f"    CONSTRAINT {quote_mssql_ident(primary_key_name)} PRIMARY KEY ({pk_sql})"
            )
        else:
            lines.append(f"    PRIMARY KEY ({pk_sql})")
    body = ",\n".join(lines)
    qualified = quoted_mssql_table(schema, table)
    object_id_literal = f"{schema}.{table}".replace("'", "''")
    return (
        f"IF OBJECT_ID(N'{object_id_literal}', 'U') IS NULL\n"
        f"BEGIN\n"
        f"CREATE TABLE {qualified} (\n{body}\n);\n"
        f"END"
    )


def build_create_index_tsql(
    *,
    schema: str,
    table: str,
    index_name: str,
    columns: list[str],
    is_unique: bool = False,
    index_type: str = "NONCLUSTERED",
    filter_definition: str | None = None,
) -> str:
    cols = ", ".join(quote_mssql_ident(c) for c in columns if c)
    if not cols:
        raise ValueError(f"Index {index_name} has no columns")
    unique = "UNIQUE " if is_unique else ""
    kind = (index_type or "NONCLUSTERED").upper()
    if kind not in {"CLUSTERED", "NONCLUSTERED"}:
        kind = "NONCLUSTERED"
    sql = (
        f"CREATE {unique}{kind} INDEX {quote_mssql_ident(index_name)} "
        f"ON {quoted_mssql_table(schema, table)} ({cols})"
    )
    if filter_definition:
        sql += f" WHERE {filter_definition.strip()}"
    return sql


def build_add_check_tsql(*, schema: str, table: str, name: str, definition: str) -> str:
    expr = (definition or "").strip()
    if not expr:
        raise ValueError(f"Check constraint {name} has no definition")
    return (
        f"ALTER TABLE {quoted_mssql_table(schema, table)} "
        f"ADD CONSTRAINT {quote_mssql_ident(name)} CHECK {expr}"
    )


def build_add_foreign_key_tsql(
    *,
    schema: str,
    table: str,
    name: str,
    columns: list[str],
    referenced_schema: str,
    referenced_table: str,
    referenced_columns: list[str],
    delete_action: str = "NO_ACTION",
    update_action: str = "NO_ACTION",
) -> str:
    src = ", ".join(quote_mssql_ident(c) for c in columns)
    ref = ", ".join(quote_mssql_ident(c) for c in referenced_columns)
    if not src or not ref:
        raise ValueError(f"Foreign key {name} is missing columns")
    sql = (
        f"ALTER TABLE {quoted_mssql_table(schema, table)} WITH NOCHECK "
        f"ADD CONSTRAINT {quote_mssql_ident(name)} FOREIGN KEY ({src}) "
        f"REFERENCES {quoted_mssql_table(referenced_schema, referenced_table)} ({ref})"
    )
    delete_clause = _referential_action("DELETE", delete_action)
    update_clause = _referential_action("UPDATE", update_action)
    if delete_clause:
        sql += f" {delete_clause}"
    if update_clause:
        sql += f" {update_clause}"
    return sql


def build_create_schema_pg(schema: str) -> str:
    return f"CREATE SCHEMA IF NOT EXISTS {quote_pg_ident_local(schema)}"


def build_create_table_pg(
    *,
    schema: str,
    table: str,
    columns: list[dict[str, Any]],
    primary_key_columns: list[str] | None = None,
) -> str:
    if not columns:
        raise ValueError(f"No columns to clone for {schema}.{table}")
    lines = []
    for col in columns:
        if col.get("is_computed"):
            continue
        ident = quote_pg_ident_local(str(col["name"]))
        typ = str(col.get("pg_type") or col.get("type_name") or "text")
        null_sql = "" if col.get("nullable", True) else " NOT NULL"
        default = col.get("default_value")
        default_sql = f" DEFAULT {default}" if default else ""
        lines.append(f"    {ident} {typ}{null_sql}{default_sql}")
    pk_cols = [c for c in (primary_key_columns or []) if c]
    if pk_cols:
        pk_sql = ", ".join(quote_pg_ident_local(c) for c in pk_cols)
        lines.append(f"    PRIMARY KEY ({pk_sql})")
    body = ",\n".join(lines)
    qualified = f"{quote_pg_ident_local(schema)}.{quote_pg_ident_local(table)}"
    return f"CREATE TABLE IF NOT EXISTS {qualified} (\n{body}\n)"


def _mssql_column_line(col: dict[str, Any]) -> str:
    name = quote_mssql_ident(str(col["name"]))
    if col.get("is_computed") and col.get("computed_definition"):
        persisted = " PERSISTED" if col.get("is_persisted") else ""
        return f"{name} AS {col['computed_definition']}{persisted}"
    typ = format_mssql_type(
        str(col.get("type_name") or "nvarchar"),
        max_length=col.get("max_length"),
        precision=col.get("precision"),
        scale=col.get("scale"),
    )
    parts = [name, typ]
    if col.get("collation_name") and str(col.get("type_name") or "").lower() in {
        "char", "varchar", "nchar", "nvarchar", "text", "ntext",
    }:
        parts.append(f"COLLATE {col['collation_name']}")
    if col.get("is_identity"):
        seed = int(col.get("identity_seed") or 1)
        incr = int(col.get("identity_increment") or 1)
        parts.append(f"IDENTITY({seed},{incr})")
    parts.append("NULL" if col.get("nullable", True) else "NOT NULL")
    default = col.get("default_value")
    if default:
        parts.append(f"DEFAULT {default}")
    return " ".join(parts)


def _referential_action(kind: str, action: str) -> str:
    normalized = (action or "NO_ACTION").upper().replace(" ", "_")
    mapping = {
        "CASCADE": f"ON {kind} CASCADE",
        "SET_NULL": f"ON {kind} SET NULL",
        "SET_DEFAULT": f"ON {kind} SET DEFAULT",
        "NO_ACTION": "",
    }
    return mapping.get(normalized, "")
