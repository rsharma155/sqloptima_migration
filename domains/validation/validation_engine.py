"""
Module: validation_engine.py
Purpose: Validation engine for schema parity, row counts, checksums, and query results
Author: Migration Platform Team
Created: 2026-05-22
Domain: Validation
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from dataclasses import dataclass, field
from enum import StrEnum
import math
from typing import Any
from uuid import UUID, uuid4

from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)


class ValidationStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"
    ERROR = "error"
    SKIPPED = "skipped"


class ValidationCategory(StrEnum):
    SCHEMA = "schema"
    ROW_COUNT = "row_count"
    AGGREGATE = "aggregate"
    CHUNK = "chunk"
    CHECKSUM = "checksum"
    QUERY_RESULT = "query_result"
    CONSTRAINT = "constraint"
    PERFORMANCE = "performance"


@dataclass
class ValidationIssue:
    """A single validation issue found."""

    category: ValidationCategory
    severity: str = "warning"
    message: str = ""
    source_value: Any | None = None
    target_value: Any | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationResult:
    """Result of validating a single object or query."""

    validation_id: UUID = field(default_factory=uuid4)
    object_name: str = ""
    category: ValidationCategory = ValidationCategory.SCHEMA
    status: ValidationStatus = ValidationStatus.PASSED
    issues: list[ValidationIssue] = field(default_factory=list)
    source_count: int | None = None
    target_count: int | None = None
    duration_ms: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)

    def is_valid(self) -> bool:
        return self.status == ValidationStatus.PASSED


@dataclass
class ValidationReport:
    """Complete validation report for a migration."""

    report_id: UUID = field(default_factory=uuid4)
    results: list[ValidationResult] = field(default_factory=list)
    total_objects: int = 0
    passed: int = 0
    failed: int = 0
    warnings: int = 0
    duration_ms: float = 0.0
    overall_status: ValidationStatus = ValidationStatus.PASSED
    validation_level: int | None = None


# Fix 4.2: type equivalence map — known-safe SQL Server → PostgreSQL type mappings.
# These are expected migration outcomes and must NOT be reported as mismatches.
_TYPE_EQUIVALENCES: dict[str, str] = {
    "NVARCHAR": "VARCHAR",
    "NCHAR": "CHAR",
    "NTEXT": "TEXT",
    "DATETIME": "TIMESTAMP",
    "DATETIME2": "TIMESTAMP",
    "SMALLDATETIME": "TIMESTAMP",
    "INT": "INTEGER",
    "TINYINT": "SMALLINT",
    "UNIQUEIDENTIFIER": "UUID",
    "BIT": "BOOLEAN",
    "MONEY": "NUMERIC",
    "SMALLMONEY": "NUMERIC",
    "IMAGE": "BYTEA",
    "VARBINARY": "BYTEA",
    "TEXT": "TEXT",
}


def _normalize_sql_type(type_str: str) -> str:
    """Normalize a SQL type string via the equivalence map for comparison."""
    base = type_str.split("(")[0].strip().upper()
    return _TYPE_EQUIVALENCES.get(base, base)


class SchemaValidator:
    """Validates schema parity between source and target."""

    async def validate_columns(
        self,
        source_columns: list[dict],
        target_columns: list[dict],
        table_name: str,
    ) -> ValidationResult:
        """Validate that columns match between source and target."""
        result = ValidationResult(
            object_name=table_name,
            category=ValidationCategory.SCHEMA,
        )

        source_names = {c.get("column_name", c.get("name", "")) for c in source_columns}
        target_names = {c.get("column_name", c.get("name", "")) for c in target_columns}

        missing_in_target = source_names - target_names
        missing_in_source = target_names - source_names
        common = source_names & target_names

        if missing_in_target:
            result.issues.append(ValidationIssue(
                category=ValidationCategory.SCHEMA,
                severity="error",
                message=f"Columns missing in target: {', '.join(missing_in_target)}",
                details={"missing": list(missing_in_target)},
            ))

        if missing_in_source:
            result.issues.append(ValidationIssue(
                category=ValidationCategory.SCHEMA,
                severity="warning",
                message=f"Extra columns in target: {', '.join(missing_in_source)}",
                details={"extra": list(missing_in_source)},
            ))

        if result.issues:
            result.status = ValidationStatus.FAILED
        else:
            result.status = ValidationStatus.PASSED

        # Validate types for common columns
        source_map = {c.get("column_name", c.get("name", "")): c for c in source_columns}
        target_map = {c.get("column_name", c.get("name", "")): c for c in target_columns}

        for col in common:
            src = source_map[col]
            tgt = target_map[col]
            src_type = src.get("data_type", src.get("type_name", "")).upper()
            tgt_type = tgt.get("data_type", tgt.get("type_name", "")).upper()
            # Fix 4.2: normalize equivalent cross-database types before comparing.
            # NVARCHAR→VARCHAR, DATETIME→TIMESTAMP etc. are expected migration mappings
            # and must NOT be reported as type mismatches.
            if _normalize_sql_type(src_type) != _normalize_sql_type(tgt_type):
                result.issues.append(ValidationIssue(
                    category=ValidationCategory.SCHEMA,
                    severity="warning",
                    message=f"Type mismatch for {col}: {src_type} -> {tgt_type}",
                    details={"column": col, "source_type": src_type, "target_type": tgt_type},
                ))

        return result


class RowCountValidator:
    """Validates row count parity between source and target."""

    async def validate(
        self,
        source_connector: Any,
        target_connector: Any,
        table_name: str,
        schema: str = "public",
        *,
        target_schema: str | None = None,
        expected_row_count: int | None = None,
    ) -> ValidationResult:
        """Compare row counts between source and target."""
        tgt_schema = target_schema or schema
        result = ValidationResult(
            object_name=f"{schema}.{table_name}",
            category=ValidationCategory.ROW_COUNT,
        )

        target_count = await self._count_target(
            target_connector, schema=tgt_schema, table=table_name,
        )
        result.target_count = target_count

        if expected_row_count is not None:
            source_count = expected_row_count
            result.source_count = source_count
            result.details["source_count_basis"] = "migration_metadata"
        else:
            source_count = await self._count_source(source_connector, schema, table_name)
            result.source_count = source_count
            result.details["source_count_basis"] = "sys.partitions_estimate"

        if expected_row_count is not None:
            counts_match = target_count == expected_row_count
        else:
            counts_match = _row_counts_within_tolerance(source_count, target_count)

        if counts_match:
            result.status = ValidationStatus.PASSED
        else:
            result.status = ValidationStatus.FAILED
            result.issues.append(ValidationIssue(
                category=ValidationCategory.ROW_COUNT,
                severity="error",
                message=(
                    f"Row count mismatch: source={source_count}, target={target_count}"
                ),
                source_value=source_count,
                target_value=target_count,
            ))

        return result

    @staticmethod
    def _q(segment: str) -> str:
        return f'"{segment}"'

    @staticmethod
    async def _count_source(connector: Any, schema: str, table: str) -> int:
        from infrastructure.sqlserver.row_count_estimate import (
            fetch_sqlserver_table_row_estimate,
        )

        return await fetch_sqlserver_table_row_estimate(connector, schema, table)

    @staticmethod
    async def _count_target(connector: Any, schema: str, table: str) -> int:
        """Fix 4.3: qualify with schema so non-public schemas count correctly."""
        try:
            rows = await connector.execute(
                f"SELECT COUNT(*) AS cnt FROM "
                f"{RowCountValidator._q(schema)}.{RowCountValidator._q(table)}"
            )
            return rows[0]["cnt"] if rows else 0
        except Exception:
            return -1


def _row_counts_within_tolerance(estimated: int, actual: int) -> bool:
    """True when DMV estimate matches target count or is within 1% (min 100 rows)."""
    if estimated == actual:
        return True
    if actual == 0:
        return estimated == 0
    return abs(estimated - actual) <= max(100, int(0.01 * actual))


class ChecksumValidator:
    """Validates data integrity using checksums."""

    async def validate(
        self,
        source_connector: Any,
        target_connector: Any,
        table_name: str,
        schema: str = "dbo",
        *,
        target_schema: str | None = None,
        algorithm: str = "CRC32",
        sample_pct: float | None = None,
    ) -> ValidationResult:
        """Compare checksums between source and target.

        NOTE: The ``CRC32`` algorithm uses ``BINARY_CHECKSUM`` on SQL Server and
        ``hashtext(ROW_TO_JSON(...))`` on PostgreSQL.  These are fundamentally
        different hash functions and will *never* produce equal values for the
        same data, making a direct comparison meaningless.

        This method therefore emits ``ValidationStatus.WARNING`` (not FAILED)
        for the CRC32 algorithm and records the raw values for diagnostics.
        Use ``AggregateValidator`` for reliable cross-database data-integrity
        checks (COUNT, SUM, MIN, MAX are mathematically consistent across both
        engines).
        """
        result = ValidationResult(
            object_name=f"{schema}.{table_name}",
            category=ValidationCategory.CHECKSUM,
        )
        result.details["algorithm"] = algorithm

        try:
            if algorithm == "CRC32":
                # Run both queries for diagnostic visibility but do NOT treat a
                # value mismatch as a data-integrity failure — the two algorithms
                # (BINARY_CHECKSUM vs hashtext) are incompatible by design.
                tgt_schema = target_schema or schema
                source_crc = await self._checksum_source(source_connector, schema, table_name, algorithm)
                target_crc = await self._checksum_target(
                    target_connector, tgt_schema, table_name, algorithm,
                )

                result.source_count = source_crc
                result.target_count = target_crc
                result.status = ValidationStatus.WARNING
                result.issues.append(ValidationIssue(
                    category=ValidationCategory.CHECKSUM,
                    severity="warning",
                    message=(
                        f"CRC32 cross-database checksum comparison is unreliable for "
                        f"{schema}.{table_name}: BINARY_CHECKSUM (SQL Server) and "
                        f"hashtext(ROW_TO_JSON) (PostgreSQL) use incompatible algorithms "
                        f"and will never match even for identical data. "
                        f"Use AggregateValidator for data-integrity checks. "
                        f"(source={source_crc}, target={target_crc})"
                    ),
                    source_value=source_crc,
                    target_value=target_crc,
                    details={"algorithm": algorithm},
                ))
            else:
                result.status = ValidationStatus.SKIPPED
                result.issues.append(ValidationIssue(
                    category=ValidationCategory.CHECKSUM,
                    severity="warning",
                    message=f"Algorithm {algorithm} not yet implemented",
                ))
        except Exception as e:
            result.status = ValidationStatus.ERROR
            result.issues.append(ValidationIssue(
                category=ValidationCategory.CHECKSUM,
                severity="error",
                message=f"Checksum validation failed: {e}",
            ))

        return result

    @staticmethod
    def _q(segment: str) -> str:
        return f'"{segment}"'

    @staticmethod
    async def _checksum_source(connector: Any, schema: str, table: str, algorithm: str) -> int:
        try:
            rows = await connector.execute(
                f"SELECT CHECKSUM_AGG(BINARY_CHECKSUM(*)) AS chk FROM {ChecksumValidator._q(schema)}.{ChecksumValidator._q(table)} WITH (TABLOCK)"
            )
            return rows[0]["chk"] if rows and rows[0]["chk"] is not None else 0
        except Exception:
            return -1

    @staticmethod
    async def _checksum_target(
        connector: Any, schema: str, table: str, algorithm: str,
    ) -> int:
        try:
            rows = await connector.execute(
                f"SELECT SUM(hashtext(ROW_TO_JSON(t)::text)) AS chk "
                f"FROM {ChecksumValidator._q(schema)}.{ChecksumValidator._q(table)} t"
            )
            return rows[0]["chk"] if rows and rows[0]["chk"] is not None else 0
        except Exception:
            return -1


class ValidationSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    BLOCKER = "blocker"


@dataclass
class CompatibilityIssue:
    severity: ValidationSeverity
    category: str
    message: str
    table: str = ""
    column: str = ""
    details: dict[str, Any] = field(default_factory=dict)


UNSUPPORTED_SQLSERVER_TYPES = {
    "sql_variant": "Use JSONB or separate typed columns",
    "hierarchyid": "Use ltree or nested set model",
    "geometry": "Use PostGIS geometry",
    "geography": "Use PostGIS geography",
    "sysname": "Use TEXT/NVARCHAR(128)",
}


class PreMigrationValidator:
    def __init__(self, source_connector: Any, target_connector: Any):
        self._source = source_connector
        self._target = target_connector

    async def validate_table(
        self, schema: str, table: str
    ) -> list[CompatibilityIssue]:
        issues: list[CompatibilityIssue] = []
        columns = await self._get_source_columns(schema, table)
        triggers = await self._get_triggers(schema, table)
        pk_cols = await self._get_pk_columns(schema, table)

        for col in columns:
            type_name = col.get("type_name", "").lower()
            if type_name in UNSUPPORTED_SQLSERVER_TYPES:
                hint = UNSUPPORTED_SQLSERVER_TYPES[type_name]
                issues.append(CompatibilityIssue(
                    severity=ValidationSeverity.BLOCKER,
                    category="datatype",
                    message=f"Unsupported datatype '{type_name}' in column '{col['name']}': {hint}",
                    table=f"{schema}.{table}",
                    column=col["name"],
                ))
            elif type_name in ("text", "ntext", "image"):
                issues.append(CompatibilityIssue(
                    severity=ValidationSeverity.WARNING,
                    category="datatype",
                    message=f"Deprecated datatype '{type_name}' in column '{col['name']}'; consider NVARCHAR(MAX)/VARBINARY(MAX)",
                    table=f"{schema}.{table}",
                    column=col["name"],
                ))

        if not pk_cols:
            issues.append(CompatibilityIssue(
                severity=ValidationSeverity.WARNING,
                category="primary_key",
                message=f"Table {schema}.{table} has no primary key — chunking will use synthetic row_number",
                table=f"{schema}.{table}",
            ))

        for t in triggers:
            if t.get("is_disabled", False):
                continue
            if t.get("type") in ("INSERT", "UPDATE", "DELETE"):
                issues.append(CompatibilityIssue(
                    severity=ValidationSeverity.WARNING,
                    category="trigger",
                    message=f"Active {t['type']} trigger '{t['name']}' on {schema}.{table} — consider disabling during bulk load",
                    table=f"{schema}.{table}",
                ))

        return issues

    async def validate_all_tables(self, tables: list[tuple[str, str]]) -> list[CompatibilityIssue]:
        all_issues: list[CompatibilityIssue] = []
        for schema, table in tables:
            issues = await self.validate_table(schema, table)
            all_issues.extend(issues)
        return all_issues

    async def validate_privileges(self) -> list[CompatibilityIssue]:
        """Warn when migration connectors use elevated database principals (§12.6)."""
        issues: list[CompatibilityIssue] = []
        issues.extend(await self._check_sqlserver_privileges())
        issues.extend(await self._check_postgres_privileges())
        return issues

    async def _check_sqlserver_privileges(self) -> list[CompatibilityIssue]:
        try:
            rows = await self._source.execute("""
                SELECT IS_SRVROLEMEMBER('sysadmin') AS is_sysadmin,
                       IS_MEMBER('db_owner') AS is_db_owner
            """)
            if not rows:
                return []
            row = rows[0]
            if row.get("is_sysadmin") == 1:
                return [CompatibilityIssue(
                    severity=ValidationSeverity.WARNING,
                    category="privilege",
                    message=(
                        "Source connection uses sysadmin — use a least-privilege "
                        "read-only account (db_datareader) for migration"
                    ),
                )]
            if row.get("is_db_owner") == 1:
                return [CompatibilityIssue(
                    severity=ValidationSeverity.WARNING,
                    category="privilege",
                    message=(
                        "Source connection is db_owner — prefer db_datareader "
                        "for read-only migration access"
                    ),
                )]
        except Exception:
            return []
        return []

    async def _check_postgres_privileges(self) -> list[CompatibilityIssue]:
        try:
            rows = await self._target.execute("""
                SELECT rolsuper AS is_superuser
                FROM pg_roles
                WHERE rolname = current_user
            """)
            if rows and rows[0].get("is_superuser"):
                return [CompatibilityIssue(
                    severity=ValidationSeverity.WARNING,
                    category="privilege",
                    message=(
                        "Target connection uses PostgreSQL superuser — use a scoped "
                        "schema owner with DDL/DML on migration objects only"
                    ),
                )]
        except Exception:
            return []
        return []

    async def _get_source_columns(
        self, schema: str, table: str
    ) -> list[dict[str, Any]]:
        try:
            rows = await self._source.execute("""
                SELECT c.name AS name, tp.name AS type_name, c.is_nullable, c.is_identity
                FROM sys.columns c
                INNER JOIN sys.types tp ON c.system_type_id = tp.system_type_id
                INNER JOIN sys.objects o ON c.object_id = o.object_id
                INNER JOIN sys.schemas s ON o.schema_id = s.schema_id
                WHERE s.name = ? AND o.name = ?
                ORDER BY c.column_id
            """, {"schema": schema, "table": table})
            return [{
                "name": r["name"],
                "type_name": r.get("type_name", ""),
                "is_nullable": r.get("is_nullable", True),
                "is_identity": r.get("is_identity", False),
            } for r in rows]
        except Exception:
            return []

    async def _get_triggers(
        self, schema: str, table: str
    ) -> list[dict[str, Any]]:
        try:
            rows = await self._source.execute("""
                SELECT t.name AS name,
                       OBJECTPROPERTY(t.object_id, 'ExecIsInsertTrigger') AS is_insert,
                       OBJECTPROPERTY(t.object_id, 'ExecIsUpdateTrigger') AS is_update,
                       OBJECTPROPERTY(t.object_id, 'ExecIsDeleteTrigger') AS is_delete,
                       t.is_disabled
                FROM sys.triggers t
                INNER JOIN sys.objects o ON t.parent_id = o.object_id
                INNER JOIN sys.schemas s ON o.schema_id = s.schema_id
                WHERE s.name = ? AND o.name = ? AND t.is_ms_shipped = 0
            """, {"schema": schema, "table": table})
            result = []
            for r in rows:
                ttype = None
                if r.get("is_insert"): ttype = "INSERT"
                elif r.get("is_update"): ttype = "UPDATE"
                elif r.get("is_delete"): ttype = "DELETE"
                result.append({
                    "name": r["name"],
                    "type": ttype,
                    "is_disabled": r.get("is_disabled", False),
                })
            return result
        except Exception:
            return []

    async def _get_pk_columns(self, schema: str, table: str) -> list[str]:
        try:
            rows = await self._source.execute("""
                SELECT c.name AS column_name
                FROM sys.indexes i
                INNER JOIN sys.index_columns ic ON i.object_id = ic.object_id AND i.index_id = ic.index_id
                INNER JOIN sys.columns c ON i.object_id = c.object_id AND ic.column_id = c.column_id
                WHERE i.is_primary_key = 1
                  AND OBJECT_SCHEMA_NAME(i.object_id) = ?
                  AND OBJECT_NAME(i.object_id) = ?
                ORDER BY ic.key_ordinal
            """, {"schema": schema, "table": table})
            return [r["column_name"] for r in rows]
        except Exception:
            return []


def _format_aggregate_value(value: Any) -> str:
    """Format aggregate values for human-readable comparison messages."""
    if value is None:
        return "NULL"
    try:
        num = float(value)
        if math.isfinite(num) and num == int(num) and abs(num) < 1e15:
            return str(int(num))
        return f"{num:.6f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)


def _normalize_aggregate_row(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize MIN/MAX/SUM/AVG keys — pyodbc often returns uppercase aliases."""
    lower = {str(k).lower(): v for k, v in row.items()}
    return {k: lower.get(k) for k in ("min", "max", "sum", "avg")}


def _aggregate_values_match(key: str, source: Any, target: Any) -> bool:
    """Compare aggregate results with rounding tolerance for cross-DB numeric drift."""
    if source is None and target is None:
        return True
    if source is None or target is None:
        return False
    try:
        s = float(source)
        t = float(target)
    except (TypeError, ValueError):
        return source == target

    if key in ("avg", "sum"):
        return math.isclose(s, t, rel_tol=1e-6, abs_tol=1e-4)
    if key in ("min", "max"):
        return math.isclose(s, t, rel_tol=0, abs_tol=1e-6)
    return s == t


_NUMERIC_SOURCE_TYPES = frozenset({
    "int", "bigint", "smallint", "tinyint", "decimal", "numeric",
    "float", "real", "money", "smallmoney", "bit",
})


class AggregateValidator:
    async def validate(
        self,
        source_connector: Any,
        target_connector: Any,
        table_name: str,
        schema: str = "dbo",
        aggregate_columns: list[str] | None = None,
        *,
        target_schema: str | None = None,
    ) -> ValidationResult:
        result = ValidationResult(
            object_name=f"{schema}.{table_name}",
            category=ValidationCategory.AGGREGATE,
        )
        tgt_schema = target_schema or schema
        functions = ["MIN", "MAX", "SUM", "AVG"]
        result.details["aggregate_functions"] = functions

        if aggregate_columns is None:
            aggregate_columns = await self._detect_numeric_columns(
                source_connector, schema, table_name,
            )

        result.details["columns_checked"] = list(aggregate_columns)
        column_results: list[dict[str, Any]] = []

        if not aggregate_columns:
            result.status = ValidationStatus.SKIPPED
            result.details["column_results"] = column_results
            result.details["skip_reason"] = "no_numeric_columns"
            result.issues.append(ValidationIssue(
                category=ValidationCategory.AGGREGATE,
                severity="warning",
                message=f"No numeric columns to compare on {schema}.{table_name}",
            ))
            return result

        for col in aggregate_columns:
            col_entry: dict[str, Any] = {"column": col, "status": "passed"}
            try:
                src = await self._get_aggregates_source(
                    source_connector, schema, table_name, col,
                )
                tgt = await self._get_aggregates_target(
                    target_connector, tgt_schema, table_name, col,
                )

                if src is None or tgt is None:
                    col_entry["status"] = "error"
                    col_entry["reason"] = "aggregate_query_failed"
                    result.issues.append(ValidationIssue(
                        category=ValidationCategory.AGGREGATE,
                        severity="error",
                        message=(
                            f"Aggregate query failed for column {col} "
                            f"on {schema}.{table_name}"
                        ),
                        details={"column": col},
                    ))
                    column_results.append(col_entry)
                    continue

                col_entry["source"] = _normalize_aggregate_row(src)
                col_entry["target"] = _normalize_aggregate_row(tgt)

                mismatches: list[str] = []
                for key in ("min", "max", "sum", "avg"):
                    s = col_entry["source"].get(key)
                    t = col_entry["target"].get(key)
                    if s is not None and t is not None and not _aggregate_values_match(key, s, t):
                        mismatches.append(
                            f"{key}: {_format_aggregate_value(s)} vs "
                            f"{_format_aggregate_value(t)}"
                        )

                if mismatches:
                    col_entry["status"] = "failed"
                    col_entry["mismatches"] = mismatches
                    result.issues.append(ValidationIssue(
                        category=ValidationCategory.AGGREGATE,
                        severity="error",
                        message=f"Aggregate mismatch for {col}: {'; '.join(mismatches)}",
                        source_value=col_entry["source"],
                        target_value=col_entry["target"],
                        details={"column": col, "mismatches": mismatches},
                    ))
            except Exception as exc:
                col_entry["status"] = "error"
                col_entry["reason"] = str(exc)
                result.issues.append(ValidationIssue(
                    category=ValidationCategory.AGGREGATE,
                    severity="error",
                    message=f"Aggregate validation error for {col}: {exc}",
                    details={"column": col},
                ))

            column_results.append(col_entry)

        result.details["column_results"] = column_results
        result.details["columns_passed"] = sum(
            1 for c in column_results if c.get("status") == "passed"
        )
        result.details["columns_failed"] = sum(
            1 for c in column_results if c.get("status") == "failed"
        )
        result.details["columns_errored"] = sum(
            1 for c in column_results if c.get("status") == "error"
        )

        if result.details["columns_failed"] or result.details["columns_errored"]:
            result.status = ValidationStatus.FAILED
        elif result.issues:
            result.status = ValidationStatus.WARNING
        else:
            result.status = ValidationStatus.PASSED

        return result

    @staticmethod
    async def _detect_numeric_columns(
        connector: Any, schema: str, table: str,
    ) -> list[str]:
        try:
            rows = await connector.execute("""
                SELECT c.name AS column_name, t.name AS type_name
                FROM sys.columns c
                INNER JOIN sys.types t ON c.user_type_id = t.user_type_id
                WHERE OBJECT_SCHEMA_NAME(c.object_id) = ?
                  AND OBJECT_NAME(c.object_id) = ?
                ORDER BY c.column_id
            """, {"schema": schema, "table": table})
            return [
                r["column_name"]
                for r in rows
                if str(r.get("type_name", "")).lower() in _NUMERIC_SOURCE_TYPES
            ]
        except Exception:
            return []

    @staticmethod
    async def _detect_pk_columns(connector: Any, schema: str, table: str) -> list[str]:
        try:
            rows = await connector.execute("""
                SELECT c.name AS column_name
                FROM sys.indexes i
                INNER JOIN sys.index_columns ic ON i.object_id = ic.object_id AND i.index_id = ic.index_id
                INNER JOIN sys.columns c ON i.object_id = c.object_id AND ic.column_id = c.column_id
                WHERE i.is_primary_key = 1
                  AND OBJECT_SCHEMA_NAME(i.object_id) = ?
                  AND OBJECT_NAME(i.object_id) = ?
                ORDER BY ic.key_ordinal
            """, {"schema": schema, "table": table})
            return [r["column_name"] for r in rows]
        except Exception:
            return []

    @staticmethod
    async def _get_aggregates_source(
        connector: Any, schema: str, table: str, column: str
    ) -> dict[str, Any] | None:
        try:
            rows = await connector.execute(
                f"SELECT MIN([{column}]) AS min, MAX([{column}]) AS max, "
                f"SUM(CAST([{column}] AS FLOAT)) AS sum, "
                f"ROUND(AVG(CAST([{column}] AS FLOAT)), 6) AS avg "
                f"FROM [{schema}].[{table}]"
            )
            return _normalize_aggregate_row(rows[0]) if rows else None
        except Exception:
            return None

    @staticmethod
    async def _get_aggregates_target(
        connector: Any, schema: str, table: str, column: str,
    ) -> dict[str, Any] | None:
        try:
            rows = await connector.execute(
                f'SELECT MIN("{column}") AS min, MAX("{column}") AS max, '
                f'SUM(CAST("{column}" AS DOUBLE PRECISION)) AS sum, '
                f'ROUND(AVG(CAST("{column}" AS DOUBLE PRECISION)), 6) AS avg '
                f'FROM "{schema}"."{table}"'
            )
            return _normalize_aggregate_row(rows[0]) if rows else None
        except Exception:
            return None


class ValidationEngine:
    """Orchestrates all validation types for a migration."""

    def __init__(
        self,
        schema_validator: SchemaValidator | None = None,
        row_count_validator: RowCountValidator | None = None,
        checksum_validator: ChecksumValidator | None = None,
        aggregate_validator: AggregateValidator | None = None,
    ):
        self._schema_validator = schema_validator or SchemaValidator()
        self._row_count_validator = row_count_validator or RowCountValidator()
        self._checksum_validator = checksum_validator or ChecksumValidator()
        self._aggregate_validator = aggregate_validator or AggregateValidator()

    async def validate_migration(
        self,
        source_connector: Any,
        target_connector: Any,
        tables: list[dict],
        run_aggregate_validation: bool = False,
        run_checksum_validation: bool = False,
    ) -> ValidationReport:
        """Run full validation on all migrated tables."""
        report = ValidationReport()
        entries_per_table = 2 + (1 if run_aggregate_validation else 0)
        if run_checksum_validation:
            entries_per_table += 1
        report.total_objects = len(tables) * entries_per_table
        logger.info("Starting validation", table_count=len(tables))

        for table_info in tables:
            table_name = table_info.get("name", "")
            schema = table_info.get("schema", "dbo")
            target_schema = table_info.get("target_schema", "public")
            if not table_name:
                logger.warning("Skipping table info entry with missing name", entry=table_info)
                continue

            logger.info(
                "Validating table",
                table=f"{schema}.{table_name}",
                target_schema=target_schema,
            )

            schema_result = await self._schema_validator.validate_columns(
                source_columns=table_info.get("source_columns", []),
                target_columns=table_info.get("target_columns", []),
                table_name=f"{schema}.{table_name}",
            )
            report.results.append(schema_result)

            row_result = await self._row_count_validator.validate(
                source_connector=source_connector,
                target_connector=target_connector,
                table_name=table_name,
                schema=schema,
                target_schema=target_schema,
            )
            report.results.append(row_result)

            if run_checksum_validation:
                cksum_result = await self._checksum_validator.validate(
                    source_connector=source_connector,
                    target_connector=target_connector,
                    table_name=table_name,
                    schema=schema,
                    target_schema=target_schema,
                )
                report.results.append(cksum_result)

            if run_aggregate_validation:
                agg_result = await self._aggregate_validator.validate(
                    source_connector=source_connector,
                    target_connector=target_connector,
                    table_name=table_name,
                    schema=schema,
                    target_schema=target_schema,
                )
                report.results.append(agg_result)

        for r in report.results:
            if r.status == ValidationStatus.PASSED:
                report.passed += 1
            elif r.status == ValidationStatus.FAILED:
                report.failed += 1
            elif r.status == ValidationStatus.WARNING:
                report.warnings += 1

        if report.failed > 0:
            report.overall_status = ValidationStatus.FAILED
        elif report.warnings > 0:
            report.overall_status = ValidationStatus.WARNING
        else:
            report.overall_status = ValidationStatus.PASSED

        logger.info(
            "Validation completed",
            passed=report.passed,
            failed=report.failed,
            warnings=report.warnings,
            overall_status=report.overall_status,
        )

        return report
