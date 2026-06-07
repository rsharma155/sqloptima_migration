"""
Module: domains/assessment/assessment_engine.py
Purpose: Rates migration complexity (SAFE/WARNING/BLOCKER) per table and estimates
         migration effort based on discovered metadata.  No I/O — pure domain logic
         that operates on already-discovered Table objects.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from domains.discovery.pii_classifier import sensitive_columns
from shared.kernel.database_object import Table
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# LOB type catalogue
# ---------------------------------------------------------------------------

_LOB_TYPES: frozenset[str] = frozenset(
    {
        "varchar(max)",
        "nvarchar(max)",
        "varbinary(max)",
        "text",
        "ntext",
        "image",
        "xml",
    }
)

_LOB_BASE_TYPES: frozenset[str] = frozenset({"text", "ntext", "image", "xml"})

# -1 in SQL Server max_length means "max" (i.e. varchar/nvarchar/varbinary MAX)
_MAX_LENGTH_SENTINEL: int = -1

# Collation suffixes that indicate case-insensitive (CI) — needs citext on PG side
_CI_SUFFIX = "_CI_"

# Unsupported types that are hard blockers
_BLOCKER_TYPES: frozenset[str] = frozenset(
    {"hierarchyid", "geography", "geometry", "sql_variant"}
)

# Row-rate estimate for throughput planning (Python extraction path, rows/minute)
_ROWS_PER_MINUTE_NORMAL: float = 60_000.0
_ROWS_PER_MINUTE_LOB: float = 5_000.0

_MASK_DEFAULTS: dict[str, str] = {
    "pii": "mask_hash",
    "phi": "mask_nullify",
    "pci": "mask_fpe_numeric",
    "credential": "mask_nullify",
}


def _recommended_mask(sensitivity: str) -> str:
    return _MASK_DEFAULTS.get(sensitivity, "mask_redact")


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------


class MigrationTier(StrEnum):
    """Readiness tier for a table or database."""

    SAFE = "SAFE"
    WARNING = "WARNING"
    BLOCKER = "BLOCKER"


@dataclass
class TableAssessment:
    """Assessment outcome for a single table."""

    table_name: str
    schema_name: str
    migration_tier: MigrationTier = MigrationTier.SAFE
    complexity_score: int = 0  # 0–100
    estimated_minutes: float = 0.0
    row_count_estimate: int = 0
    lob_columns: list[str] = field(default_factory=list)
    ci_collation_columns: list[str] = field(default_factory=list)
    blocker_types: list[str] = field(default_factory=list)
    unsupported_type_columns: list[dict[str, str]] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    prerequisites: list[str] = field(default_factory=list)
    sensitive_columns: list[dict[str, str]] = field(default_factory=list)

    @property
    def qualified_name(self) -> str:
        return f"{self.schema_name}.{self.table_name}"


@dataclass
class DatabaseAssessment:
    """Aggregate assessment for an entire database / schema set."""

    database_name: str
    tables: list[TableAssessment] = field(default_factory=list)
    overall_tier: MigrationTier = MigrationTier.SAFE
    total_tables: int = 0
    safe_count: int = 0
    warning_count: int = 0
    blocker_count: int = 0
    estimated_total_minutes: float = 0.0
    global_prerequisites: list[str] = field(default_factory=list)
    # Supplemental metadata set by discovery queries outside this engine
    cdc_enabled_db: bool = False
    linked_server_refs: list[dict[str, Any]] = field(default_factory=list)
    global_temp_table_refs: list[dict[str, Any]] = field(default_factory=list)
    agent_jobs: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Assessment engine
# ---------------------------------------------------------------------------


class AssessmentEngine:
    """Rates migration complexity and readiness from discovered Table objects.

    All logic is pure — no database I/O.  Feed it the output of
    SqlServerMetadataDiscovery.discover_tables() and it returns assessments.

    Example::

        engine = AssessmentEngine()
        db_assessment = engine.assess_database("AdventureWorks", tables)
    """

    # Score thresholds
    _BLOCKER_THRESHOLD: int = 80
    _WARNING_THRESHOLD: int = 30

    def assess_table(
        self,
        table: Table,
        cdc_enabled_db: bool = False,
    ) -> TableAssessment:
        """Produce a complexity assessment for a single table."""
        score = 0
        lob_cols: list[str] = []
        ci_cols: list[str] = []
        blocker_types: list[str] = []
        unsupported_type_columns: list[dict[str, str]] = []
        blockers: list[str] = []
        warnings: list[str] = []
        prereqs: list[str] = []

        for col in table.columns:
            type_lower = col.data_type.type_name.lower()
            max_len = col.data_type.max_length

            # ---- Blocker types ----
            if type_lower in _BLOCKER_TYPES:
                blocker_types.append(col.column_name)
                unsupported_type_columns.append(
                    {"column_name": col.column_name, "source_type": type_lower}
                )
                blockers.append(
                    f"Column '{col.column_name}' uses unsupported type '{type_lower}' "
                    f"— choose a PostgreSQL target type in the migration wizard to proceed"
                )
                score += 40

            # ---- LOB detection ----
            is_lob = type_lower in _LOB_BASE_TYPES or (
                type_lower in ("varchar", "nvarchar", "varbinary")
                and max_len == _MAX_LENGTH_SENTINEL
            )
            if is_lob:
                lob_cols.append(col.column_name)
                score += 8

            # ---- CI collation ----
            collation = col.collation_name or ""
            if _CI_SUFFIX in collation.upper():
                ci_cols.append(col.column_name)
                score += 5

            # ---- Computed columns ----
            if col.is_computed:
                score += 5
                warnings.append(
                    f"Column '{col.column_name}' is computed — verify PostgreSQL "
                    f"GENERATED ALWAYS AS expression is equivalent"
                )

        # ---- No primary key ----
        # Table.columns being non-empty doesn't mean there's a PK; check identity as proxy
        has_identity = any(c.is_identity for c in table.columns)
        if not has_identity and table.columns:
            score += 10
            warnings.append(
                "No IDENTITY column detected — chunk planning will fall back to "
                "OFFSET/FETCH which is slower for large tables"
            )

        # ---- Temporal tables ----
        if getattr(table, "is_temporal", False):
            score += 20
            warnings.append(
                "Temporal (system-versioned) table — history table must be migrated "
                "separately; versioning must be reconfigured on PostgreSQL"
            )
            prereqs.append("Disable temporal versioning before migration; re-enable after")

        # ---- Memory-optimised ----
        if getattr(table, "is_memory_optimized", False):
            score += 15
            warnings.append(
                "Memory-optimised (In-Memory OLTP) table — "
                "requires conversion to a standard disk-based table"
            )

        # ---- Large table ----
        rows = table.row_count_estimate or 0
        if rows > 1_000_000:
            score += 10
            prereqs.append(
                f"Table has ~{rows:,} rows — allocate sufficient migration window "
                f"and verify target disk capacity"
            )
        if rows > 100_000_000:
            score += 10
            warnings.append(
                f"Very large table ({rows:,} rows) — consider partitioned extraction "
                f"with multiple parallel workers"
            )

        # ---- LOB aggregate warning ----
        if lob_cols:
            warnings.append(
                f"LOB columns ({', '.join(lob_cols)}) require separate streaming pass "
                f"— expect lower throughput on this table"
            )
            if not cdc_enabled_db:
                prereqs.append(
                    "CDC not detected — LOB-heavy tables cannot use incremental CDC sync; "
                    "schedule a maintenance window for cutover"
                )

        # ---- CI collation aggregate warning ----
        if ci_cols:
            warnings.append(
                f"Case-insensitive collation on columns ({', '.join(ci_cols)}) — "
                f"install the citext extension on PostgreSQL or use lower() indexes"
            )
            prereqs.append("CREATE EXTENSION citext; on target database")

        # ---- PII / sensitive column detection (§12.2) ----
        col_names = [c.column_name for c in table.columns]
        sens = sensitive_columns(col_names)
        sensitive_meta = [
            {
                "column": s.column_name,
                "sensitivity": s.sensitivity.value,
                "reason": s.reason,
                "recommended_mask": _recommended_mask(s.sensitivity.value),
            }
            for s in sens
        ]
        if sens:
            score += min(15, len(sens) * 3)
            warnings.append(
                f"Sensitive data detected in {len(sens)} column(s): "
                f"{', '.join(s.column_name for s in sens)} — "
                f"configure masking transforms before migrating to non-production targets"
            )
            prereqs.append(
                "Review column_transforms / column_sensitivity on migration plan; "
                "default masks: PII→hash, PHI/CREDENTIAL→nullify, PCI→last-four"
            )

        # ---- Tier determination ----
        score = min(score, 100)
        if blockers or score >= self._BLOCKER_THRESHOLD:
            tier = MigrationTier.BLOCKER
        elif warnings or score >= self._WARNING_THRESHOLD:
            tier = MigrationTier.WARNING
        else:
            tier = MigrationTier.SAFE

        # ---- Estimated migration time ----
        if lob_cols:
            rate = _ROWS_PER_MINUTE_LOB
        else:
            rate = _ROWS_PER_MINUTE_NORMAL
        estimated_minutes = max(0.1, rows / rate) if rows else 0.1

        return TableAssessment(
            table_name=table.object_name,
            schema_name=table.schema_name,
            migration_tier=tier,
            complexity_score=score,
            estimated_minutes=round(estimated_minutes, 2),
            row_count_estimate=rows,
            lob_columns=lob_cols,
            ci_collation_columns=ci_cols,
            blocker_types=blocker_types,
            unsupported_type_columns=unsupported_type_columns,
            blockers=blockers,
            warnings=warnings,
            prerequisites=prereqs,
            sensitive_columns=sensitive_meta,
        )

    async def _check_chunking_column_indexed(
        self,
        source: Any,
        schema: str,
        table: str,
        column: str,
    ) -> bool:
        """Fix 9.2: query sys.indexes to verify the chunking column is indexed.

        Uses ? placeholders (pyodbc style) so schema/table/column names are never
        f-string-interpolated into the SQL — avoids SQL injection and identifier quoting issues.
        Excludes heap (type=0) since heaps carry no index benefit.
        """
        sql = """
            SELECT 1
            FROM sys.indexes i
            JOIN sys.index_columns ic
              ON ic.object_id = i.object_id AND ic.index_id = i.index_id
            JOIN sys.columns c
              ON c.object_id = ic.object_id AND c.column_id = ic.column_id
            JOIN sys.tables t
              ON t.object_id = i.object_id
            JOIN sys.schemas s
              ON s.schema_id = t.schema_id
            WHERE s.name = ?
              AND t.name = ?
              AND c.name = ?
              AND i.type > 0
        """
        rows = await source.execute(sql, schema, table, column)
        return len(rows) > 0

    async def assess_table_with_source(
        self,
        table: "Table",
        source: Any,
        chunk_col: str | None = None,
    ) -> "TableAssessment":
        """Fix 9.2: like assess_table but also checks whether the chunk column is indexed.

        When ``chunk_col`` is given and is not indexed on the source, a WARNING
        is added so operators know query performance will degrade during extraction.
        """
        assessment = self.assess_table(table)
        if chunk_col:
            is_indexed = await self._check_chunking_column_indexed(
                source, table.schema_name, table.object_name, chunk_col
            )
            if not is_indexed:
                assessment.warnings.append(
                    f"Chunk column '{chunk_col}' has no index on "
                    f"{table.schema_name}.{table.object_name} — "
                    "extraction will perform a full table scan per chunk, severely "
                    "degrading throughput for large tables. Add an index before migrating."
                )
                if assessment.migration_tier == MigrationTier.SAFE:
                    assessment.migration_tier = MigrationTier.WARNING
        return assessment

    def assess_database(
        self,
        database_name: str,
        tables: list[Table],
        cdc_enabled_db: bool = False,
        linked_server_refs: list[dict[str, Any]] | None = None,
        global_temp_table_refs: list[dict[str, Any]] | None = None,
        agent_jobs: list[dict[str, Any]] | None = None,
    ) -> DatabaseAssessment:
        """Assess an entire database from a flat list of discovered tables."""
        linked_server_refs = linked_server_refs or []
        global_temp_table_refs = global_temp_table_refs or []
        agent_jobs = agent_jobs or []
        assessments: list[TableAssessment] = []
        for table in tables:
            ta = self.assess_table(table, cdc_enabled_db=cdc_enabled_db)
            assessments.append(ta)
            logger.debug(
                "table_assessed",
                table=ta.qualified_name,
                tier=ta.migration_tier,
                score=ta.complexity_score,
            )

        safe = sum(1 for a in assessments if a.migration_tier == MigrationTier.SAFE)
        warning = sum(1 for a in assessments if a.migration_tier == MigrationTier.WARNING)
        blocker = sum(1 for a in assessments if a.migration_tier == MigrationTier.BLOCKER)

        if blocker > 0:
            overall = MigrationTier.BLOCKER
        elif warning > 0:
            overall = MigrationTier.WARNING
        else:
            overall = MigrationTier.SAFE

        total_minutes = sum(a.estimated_minutes for a in assessments)

        global_prereqs: list[str] = []
        if not cdc_enabled_db:
            global_prereqs.append(
                "SQL Server CDC is not enabled — enable with "
                "EXEC sys.sp_cdc_enable_db before starting incremental sync"
            )
        if linked_server_refs:
            servers = {r.get("referenced_server", "") for r in linked_server_refs}
            global_prereqs.append(
                f"Linked server references detected ({', '.join(sorted(servers))}) — "
                f"these cannot be migrated automatically; update callsites to use "
                f"direct connections or PostgreSQL FDW (postgres_fdw / dblink)"
            )
        if global_temp_table_refs:
            objects = {r.get("object_name", "") for r in global_temp_table_refs}
            global_prereqs.append(
                f"Global temporary table (##) references found in "
                f"{len(objects)} object(s) ({', '.join(sorted(objects))}) — "
                f"PostgreSQL has no equivalent; refactor to session-scoped TEMP "
                f"tables or application-level temporary storage before migrating"
            )
        if agent_jobs:
            job_names = {r.get("job_name", "") for r in agent_jobs}
            global_prereqs.append(
                f"SQL Server Agent job(s) reference this database "
                f"({', '.join(sorted(job_names))}) — "
                f"recreate these as pg_cron jobs or external schedulers after cutover"
            )

        db_assessment = DatabaseAssessment(
            database_name=database_name,
            tables=assessments,
            overall_tier=overall,
            total_tables=len(assessments),
            safe_count=safe,
            warning_count=warning,
            blocker_count=blocker,
            estimated_total_minutes=round(total_minutes, 2),
            global_prerequisites=global_prereqs,
            cdc_enabled_db=cdc_enabled_db,
            linked_server_refs=linked_server_refs,
            global_temp_table_refs=global_temp_table_refs,
            agent_jobs=agent_jobs,
        )

        logger.info(
            "database_assessed",
            database=database_name,
            total=len(assessments),
            safe=safe,
            warning=warning,
            blocker=blocker,
            overall_tier=overall,
        )
        return db_assessment
