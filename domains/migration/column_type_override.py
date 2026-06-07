"""
Module: column_type_override.py
Purpose: User-approved PostgreSQL target types for unsupported SQL Server columns.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from domains.assessment.assessment_engine import (
    DatabaseAssessment,
    MigrationTier,
    TableAssessment,
)

UNSUPPORTED_SOURCE_TYPES: frozenset[str] = frozenset(
    {"hierarchyid", "geography", "geometry", "sql_variant"}
)

# PostgreSQL types the Go binary COPY encoder sends as UTF-8 text — not native binary.
_LOAD_AS_TEXT_FOR_COPY: frozenset[str] = frozenset(
    {"jsonb", "json", "ltree", "geometry", "geography"}
)


@dataclass(frozen=True, slots=True)
class ColumnTypeOverrideOption:
    """A user-selectable PostgreSQL mapping for an unsupported SQL Server type."""

    option_id: str
    pg_ddl_type: str
    label: str
    description: str
    extract_type: str
    cast_template: str
    requires_extension: str | None = None
    fidelity: str = "partial"

    def source_cast_expression(self, column_name: str) -> str:
        """SQL Server SELECT expression (bracket-quoted column)."""
        col = _quote_mssql_ident(column_name)
        return self.cast_template.format(col=col)


@dataclass(frozen=True, slots=True)
class ResolvedColumnTypeOverride:
    """Fully resolved override applied during provisioning and extraction."""

    table_name: str
    column_name: str
    source_type: str
    option_id: str
    pg_ddl_type: str
    extract_type: str
    source_cast_expression: str
    requires_extension: str | None = None

    @property
    def override_key(self) -> str:
        return override_key(self.table_name, self.column_name)

    @property
    def load_pg_ddl_type(self) -> str:
        """DDL type for bulk COPY load (text-safe for binary COPY encoder)."""
        if self.pg_ddl_type in _LOAD_AS_TEXT_FOR_COPY:
            return "text"
        return self.pg_ddl_type

    @property
    def needs_finalize_type_cast(self) -> bool:
        return self.load_pg_ddl_type != self.pg_ddl_type

    def finalize_cast_using_sql(self) -> str | None:
        """USING expression for ALTER COLUMN … TYPE after data load."""
        if not self.needs_finalize_type_cast:
            return None
        from shared.kernel.ddl_identifier import quote_pg_ident

        pg_col = quote_pg_ident(self.column_name)
        match self.pg_ddl_type:
            case "jsonb" | "json":
                return f"{pg_col}::{self.pg_ddl_type}"
            case "ltree":
                return f"{pg_col}::ltree"
            case "geometry":
                return f"ST_GeomFromText({pg_col})::geometry"
            case "geography":
                return f"ST_GeomFromText({pg_col})::geography"
            case _:
                return f"{pg_col}::{self.pg_ddl_type}"


def column_type_casts_for_plan(
    resolved: dict[str, ResolvedColumnTypeOverride],
    table_name: str,
) -> list[dict[str, str]]:
    """Serialize deferred type casts stored on migration_table_plans.plan_config."""
    casts: list[dict[str, str]] = []
    for ro in resolved.values():
        if ro.table_name != table_name or not ro.needs_finalize_type_cast:
            continue
        using_sql = ro.finalize_cast_using_sql()
        if using_sql:
            casts.append(
                {
                    "column_name": ro.column_name,
                    "load_pg_type": ro.load_pg_ddl_type,
                    "final_pg_type": ro.pg_ddl_type,
                    "using_sql": using_sql,
                }
            )
    return casts


TYPE_OVERRIDE_CATALOG: dict[str, tuple[ColumnTypeOverrideOption, ...]] = {
    "sql_variant": (
        ColumnTypeOverrideOption(
            option_id="sql_variant_jsonb",
            pg_ddl_type="jsonb",
            label="JSONB",
            description="Cast to Unicode text, load as TEXT, then finalize to JSONB after migration.",
            extract_type="nvarchar",
            cast_template="CAST({col} AS nvarchar(max))",
            fidelity="partial",
        ),
        ColumnTypeOverrideOption(
            option_id="sql_variant_text",
            pg_ddl_type="text",
            label="TEXT",
            description="Cast to Unicode text — preserves readable values, no JSON validation.",
            extract_type="nvarchar",
            cast_template="CAST({col} AS nvarchar(max))",
            fidelity="partial",
        ),
        ColumnTypeOverrideOption(
            option_id="sql_variant_bytea",
            pg_ddl_type="bytea",
            label="BYTEA (binary)",
            description="Raw binary representation — use when downstream ETL handles decoding.",
            extract_type="varbinary",
            cast_template="CAST({col} AS varbinary(max))",
            fidelity="lossy",
        ),
    ),
    "hierarchyid": (
        ColumnTypeOverrideOption(
            option_id="hierarchyid_text",
            pg_ddl_type="text",
            label="TEXT",
            description="String path via CAST — portable, no extension required.",
            extract_type="nvarchar",
            cast_template="CAST({col} AS nvarchar(900))",
            fidelity="partial",
        ),
        ColumnTypeOverrideOption(
            option_id="hierarchyid_ltree",
            pg_ddl_type="ltree",
            label="ltree (extension)",
            description="Hierarchy path as ltree — requires CREATE EXTENSION ltree on target.",
            extract_type="nvarchar",
            cast_template="{col}.ToString()",
            requires_extension="ltree",
            fidelity="partial",
        ),
        ColumnTypeOverrideOption(
            option_id="hierarchyid_varchar",
            pg_ddl_type="varchar(900)",
            label="VARCHAR(900)",
            description="Fixed-max varchar — same string cast as TEXT.",
            extract_type="nvarchar",
            cast_template="CAST({col} AS nvarchar(900))",
            fidelity="partial",
        ),
    ),
    "geometry": (
        ColumnTypeOverrideOption(
            option_id="geometry_postgis",
            pg_ddl_type="geometry",
            label="geometry (PostGIS)",
            description="Well-known text into PostGIS geometry — requires postgis extension.",
            extract_type="nvarchar",
            cast_template="{col}.STAsText()",
            requires_extension="postgis",
            fidelity="partial",
        ),
        ColumnTypeOverrideOption(
            option_id="geometry_text_wkt",
            pg_ddl_type="text",
            label="TEXT (WKT)",
            description="Store WKT text — convert to geometry manually after migration.",
            extract_type="nvarchar",
            cast_template="{col}.STAsText()",
            fidelity="partial",
        ),
    ),
    "geography": (
        ColumnTypeOverrideOption(
            option_id="geography_postgis",
            pg_ddl_type="geography",
            label="geography (PostGIS)",
            description="Well-known text into PostGIS geography — requires postgis extension.",
            extract_type="nvarchar",
            cast_template="{col}.STAsText()",
            requires_extension="postgis",
            fidelity="partial",
        ),
        ColumnTypeOverrideOption(
            option_id="geography_text_wkt",
            pg_ddl_type="text",
            label="TEXT (WKT)",
            description="Store WKT text — convert to geography manually after migration.",
            extract_type="nvarchar",
            cast_template="{col}.STAsText()",
            fidelity="partial",
        ),
    ),
}


def override_key(table_name: str, column_name: str) -> str:
    return f"{table_name}.{column_name}"


def parse_override_key(key: str) -> tuple[str, str]:
    table, _, column = key.partition(".")
    if not table or not column:
        raise ValueError(f"Invalid column type override key: {key!r}")
    return table, column


def options_for_source_type(source_type: str) -> list[ColumnTypeOverrideOption]:
    base = source_type.strip().lower()
    if "(" in base:
        base = base[: base.index("(")].strip()
    return list(TYPE_OVERRIDE_CATALOG.get(base, ()))


def catalog_for_api() -> dict[str, list[dict[str, Any]]]:
    """Serialize override options for REST clients."""
    out: dict[str, list[dict[str, Any]]] = {}
    for source_type, options in TYPE_OVERRIDE_CATALOG.items():
        out[source_type] = [
            {
                "option_id": o.option_id,
                "pg_ddl_type": o.pg_ddl_type,
                "label": o.label,
                "description": o.description,
                "requires_extension": o.requires_extension,
                "fidelity": o.fidelity,
            }
            for o in options
        ]
    return out


def lookup_option(source_type: str, option_id: str) -> ColumnTypeOverrideOption | None:
    for opt in options_for_source_type(source_type):
        if opt.option_id == option_id:
            return opt
    return None


def is_unsupported_type_only_blocker(ta: TableAssessment) -> bool:
    """True when every blocker message is an unsupported SQL Server type."""
    if not ta.blocker_types:
        return False
    if not ta.blockers:
        return False
    return all("uses unsupported type" in msg for msg in ta.blockers)


def missing_type_override_keys(
    ta: TableAssessment,
    column_type_overrides: dict[str, str],
) -> list[str]:
    """Return override keys still required for a table assessment."""
    missing: list[str] = []
    for col in ta.blocker_types:
        key = override_key(ta.table_name, col)
        if key not in column_type_overrides:
            missing.append(key)
    return missing


def table_blocked_after_overrides(
    ta: TableAssessment,
    column_type_overrides: dict[str, str],
) -> tuple[bool, list[str]]:
    """Whether a BLOCKER table remains blocked after user overrides."""
    if ta.migration_tier != MigrationTier.BLOCKER:
        return False, []

    if is_unsupported_type_only_blocker(ta):
        missing = missing_type_override_keys(ta, column_type_overrides)
        if not missing:
            return False, []
        return True, [
            f"Choose a PostgreSQL target type for: {', '.join(missing)}"
        ]

    return True, ta.blockers or [f"Table has BLOCKER complexity (score {ta.complexity_score}/100)"]


def resolve_overrides_for_tables(
    assessment: DatabaseAssessment,
    table_names: list[str],
    column_type_overrides: dict[str, str],
) -> dict[str, ResolvedColumnTypeOverride]:
    """Validate and resolve user override selections."""
    by_name = {ta.table_name.lower(): ta for ta in assessment.tables}
    resolved: dict[str, ResolvedColumnTypeOverride] = {}
    errors: list[str] = []

    for key, option_id in column_type_overrides.items():
        try:
            table_name, column_name = parse_override_key(key)
        except ValueError as exc:
            errors.append(str(exc))
            continue

        ta = by_name.get(table_name.lower())
        if ta is None:
            errors.append(f"Override {key!r}: table not in assessment")
            continue

        if column_name not in ta.blocker_types:
            errors.append(f"Override {key!r}: column is not an unsupported-type blocker")
            continue

        source_type = _source_type_for_column(ta, column_name)
        if source_type is None:
            errors.append(f"Override {key!r}: could not determine source SQL Server type")
            continue

        option = lookup_option(source_type, option_id)
        if option is None:
            errors.append(
                f"Override {key!r}: unknown option_id {option_id!r} for type {source_type!r}"
            )
            continue

        ro = ResolvedColumnTypeOverride(
            table_name=ta.table_name,
            column_name=column_name,
            source_type=source_type,
            option_id=option_id,
            pg_ddl_type=option.pg_ddl_type,
            extract_type=option.extract_type,
            source_cast_expression=option.source_cast_expression(column_name),
            requires_extension=option.requires_extension,
        )
        resolved[ro.override_key] = ro

    for name in table_names:
        ta = by_name.get(name.lower())
        if ta is None:
            continue
        if is_unsupported_type_only_blocker(ta):
            missing = missing_type_override_keys(ta, column_type_overrides)
            if missing:
                errors.append(
                    f"Table {ta.table_name}: missing type overrides for {', '.join(missing)}"
                )

    if errors:
        raise ValueError("; ".join(errors))

    return resolved


def overrides_by_table(
    resolved: dict[str, ResolvedColumnTypeOverride],
) -> dict[str, dict[str, ResolvedColumnTypeOverride]]:
    grouped: dict[str, dict[str, ResolvedColumnTypeOverride]] = {}
    for ro in resolved.values():
        grouped.setdefault(ro.table_name, {})[ro.column_name] = ro
    return grouped


def _source_type_for_column(ta: TableAssessment, column_name: str) -> str | None:
    for entry in ta.unsupported_type_columns:
        if entry.get("column_name") == column_name:
            return str(entry.get("source_type", "")).lower() or None
    if column_name in ta.blocker_types:
        # Fallback when unsupported_type_columns not populated (legacy assessments)
        return "sql_variant"
    return None


def _quote_mssql_ident(ident: str) -> str:
    return "[" + ident.replace("]", "]]") + "]"


def source_select_expression(
    table_name: str,
    column_name: str,
    source_type: str,
    resolved_overrides: dict[str, ResolvedColumnTypeOverride] | None = None,
) -> str:
    """Return a pyodbc-safe SELECT fragment for one column (cast when needed)."""
    overrides = resolved_overrides or {}
    key = override_key(table_name, column_name)
    if key in overrides:
        return f"{overrides[key].source_cast_expression} AS {_quote_mssql_ident(column_name)}"

    base = source_type.strip().lower()
    if "(" in base:
        base = base[: base.index("(")].strip()
    if base in UNSUPPORTED_SOURCE_TYPES:
        options = options_for_source_type(base)
        if options:
            return (
                f"{options[0].source_cast_expression(column_name)} "
                f"AS {_quote_mssql_ident(column_name)}"
            )
    return _quote_mssql_ident(column_name)


def build_source_select_list(
    table_name: str,
    columns: list[tuple[str, str]],
    resolved_overrides: dict[str, ResolvedColumnTypeOverride] | None = None,
) -> str:
    """Build comma-separated SELECT list for SQL Server (metadata-driven, no SELECT *)."""
    return ", ".join(
        source_select_expression(table_name, name, source_type, resolved_overrides)
        for name, source_type in columns
    )


async def discover_table_column_types(
    connector: Any,
    database: str,
    schema: str,
    table: str,
) -> list[tuple[str, str]]:
    """Return (column_name, source_type) ordered by ordinal position."""
    from infrastructure.sqlserver.sqlserver_discovery import SqlServerMetadataDiscovery

    discovery = SqlServerMetadataDiscovery(connector)
    discovered = await discovery.discover_tables(database, schema)
    meta = next((t for t in discovered if t.object_name.lower() == table.lower()), None)
    if not meta or not meta.columns:
        return []
    ordered = sorted(meta.columns, key=lambda c: c.ordinal_position)
    return [
        (c.column_name, (c.data_type.type_name or "varchar").lower())
        for c in ordered
        if c.data_type and c.data_type.type_name
    ]


async def build_safe_source_select_list(
    connector: Any,
    database: str,
    schema: str,
    table: str,
    resolved_overrides: dict[str, ResolvedColumnTypeOverride] | None = None,
) -> str:
    columns = await discover_table_column_types(connector, database, schema, table)
    if not columns:
        raise ValueError(f"No columns discovered for {schema}.{table}")
    return build_source_select_list(table, columns, resolved_overrides)


@dataclass(frozen=True, slots=True)
class SourceRowFetchResult:
    """Result of fetching one SQL Server row by primary key."""

    row: dict[str, Any] | None = None
    fetch_error: str | None = None


async def fetch_source_row_safe(
    connector: Any,
    schema: str,
    table: str,
    pk_columns: list[str],
    pk_values: dict[str, Any],
    *,
    database: str,
    resolved_overrides: dict[str, ResolvedColumnTypeOverride] | None = None,
) -> SourceRowFetchResult:
    """Fetch one source row using cast-safe SELECT (no ``SELECT *``)."""
    from shared.logging.structured_logging import get_logger

    log = get_logger(__name__)
    select_list = await build_safe_source_select_list(
        connector, database, schema, table, resolved_overrides,
    )
    where = " AND ".join(f"{_quote_mssql_ident(c)} = ?" for c in pk_columns)
    params = {c: pk_values[c] for c in pk_columns}
    try:
        rows = await connector.execute(
            f"SELECT {select_list} FROM [{schema}].[{table}] WHERE {where}",
            params,
        )
        if rows:
            return SourceRowFetchResult(row=dict(rows[0]))
        return SourceRowFetchResult()
    except Exception as exc:
        log.warning(
            "fetch_source_row_safe_failed",
            schema=schema,
            table=table,
            pk_values=pk_values,
            error=str(exc),
        )
        return SourceRowFetchResult(fetch_error=str(exc))


async def fetch_source_rows_top_n_safe(
    connector: Any,
    schema: str,
    table: str,
    *,
    database: str,
    limit: int,
    order_column: str,
    resolved_overrides: dict[str, ResolvedColumnTypeOverride] | None = None,
) -> list[dict[str, Any]]:
    """Fetch top-N rows with cast-safe SELECT (replaces ``SELECT TOP n *``)."""
    select_list = await build_safe_source_select_list(
        connector, database, schema, table, resolved_overrides,
    )
    rows = await connector.execute(
        f"SELECT TOP {limit} {select_list} "
        f"FROM [{schema}].[{table}] ORDER BY [{order_column}]",
    )
    return [dict(r) for r in rows]


def load_resolved_overrides_from_job(job: Any) -> dict[str, ResolvedColumnTypeOverride]:
    raw = getattr(job, "column_type_overrides", None) or {}
    resolved: dict[str, ResolvedColumnTypeOverride] = {}
    for key, data in raw.items():
        if isinstance(data, ResolvedColumnTypeOverride):
            resolved[key] = data
        elif isinstance(data, dict):
            resolved[key] = ResolvedColumnTypeOverride(**data)
    return resolved

