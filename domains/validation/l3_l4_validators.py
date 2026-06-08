"""
Module: domains/validation/l3_l4_validators.py
Purpose: L3 (chunk-boundary hash/aggregate) and L4 (statistical sampling) validators.
         Both use database-pushdown queries — no rows are pulled into Python memory.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import math
from typing import Any

from domains.validation.validation_engine import (
    ValidationCategory,
    ValidationIssue,
    ValidationResult,
    ValidationStatus,
)
from domains.migration.column_type_override import (
    ResolvedColumnTypeOverride,
    SourceRowFetchResult,
    fetch_source_row_safe,
)
from shared.kernel.ddl_identifier import quote_pg_ident
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)


def _pg_table_ref(schema: str, table: str) -> str:
    return f"{quote_pg_ident(schema)}.{quote_pg_ident(table)}"


def _pk_key_label(pk_columns: list[str], pk_values: dict[str, Any]) -> str:
    if len(pk_columns) == 1:
        col = pk_columns[0]
        return f"{col}={pk_values[col]!r}"
    parts = ", ".join(f"{c}={pk_values[c]!r}" for c in pk_columns)
    return f"({parts})"


# ---------------------------------------------------------------------------
# L3 — Chunk-boundary validation
# ---------------------------------------------------------------------------

class L3ChunkHashValidator:
    """Validates data integrity at chunk-boundary granularity.

    For each (pk_start, pk_end) range supplied by the caller, computes:
    - ``COUNT(*)`` — must match on both sides
    - ``MIN`` / ``MAX`` of the primary-key column — must match on both sides
      (single-column PK only)
    - Numeric column ``SUM`` (if *numeric_columns* provided) — must match

    This is stronger than a single global row-count (L1) because it catches
    gaps or duplicates within specific key ranges.

    Note on cross-database hashing:
        SQL Server's ``CHECKSUM_AGG(BINARY_CHECKSUM(*))`` and PostgreSQL's
        ``hashtext`` produce different values for the same data because they
        use different algorithms.  Therefore L3 compares *counts and
        aggregates per range* rather than hash digests, which is both
        portable and sufficient for detecting data loss or duplication.
    """

    async def validate_chunk(
        self,
        source_connector: Any,
        target_connector: Any,
        table_name: str,
        pk_columns: list[str],
        pk_start: Any,
        pk_end: Any,
        schema: str = "dbo",
        target_schema: str = "public",
        numeric_columns: list[str] | None = None,
    ) -> ValidationResult:
        """Validate a single chunk boundary range."""
        result = ValidationResult(
            object_name=f"{schema}.{table_name}[{pk_start}..{pk_end}]",
            category=ValidationCategory.CHUNK,
        )
        result.details["pk_start"] = pk_start
        result.details["pk_end"] = pk_end
        result.details["pk_columns"] = list(pk_columns)

        src = await self._query_source(
            source_connector, schema, table_name, pk_columns,
            pk_start, pk_end, numeric_columns or [],
        )
        tgt = await self._query_target(
            target_connector, target_schema, table_name, pk_columns,
            pk_start, pk_end, numeric_columns or [],
        )

        if src is None or tgt is None:
            result.status = ValidationStatus.ERROR
            result.issues.append(
                ValidationIssue(
                    category=ValidationCategory.CHUNK,
                    severity="error",
                    message="Chunk query failed on source or target",
                )
            )
            return result

        mismatches: list[str] = []
        src_count = src.get("cnt", 0)
        tgt_count = tgt.get("cnt", 0)
        if src_count != tgt_count:
            mismatches.append(f"count: src={src_count} tgt={tgt_count}")

        if len(pk_columns) == 1:
            for agg in ("min_pk", "max_pk"):
                sv, tv = src.get(agg), tgt.get(agg)
                if sv is not None and tv is not None and str(sv) != str(tv):
                    mismatches.append(f"{agg}: src={sv} tgt={tv}")

        for col in (numeric_columns or []):
            key = f"sum_{col}"
            sv, tv = src.get(key), tgt.get(key)
            if sv is not None and tv is not None:
                try:
                    if not math.isclose(float(sv), float(tv), rel_tol=1e-9):
                        mismatches.append(f"sum({col}): src={sv} tgt={tv}")
                except (TypeError, ValueError):
                    if str(sv) != str(tv):
                        mismatches.append(f"sum({col}): src={sv} tgt={tv}")

        if mismatches:
            result.status = ValidationStatus.FAILED
            result.source_count = src_count
            result.target_count = tgt_count
            for m in mismatches:
                result.issues.append(
                    ValidationIssue(
                        category=ValidationCategory.CHUNK,
                        severity="error",
                        message=f"Chunk mismatch — {m}",
                        source_value=src,
                        target_value=tgt,
                    )
                )
        else:
            result.status = ValidationStatus.PASSED
            result.source_count = src_count
            result.target_count = tgt_count

        return result

    async def validate_all_chunks(
        self,
        source_connector: Any,
        target_connector: Any,
        table_name: str,
        pk_columns: list[str],
        chunks: list[tuple[Any, Any]],
        schema: str = "dbo",
        target_schema: str = "public",
        numeric_columns: list[str] | None = None,
    ) -> list[ValidationResult]:
        """Validate every chunk in *chunks* (list of (pk_start, pk_end) pairs)."""
        results = []
        for pk_start, pk_end in chunks:
            r = await self.validate_chunk(
                source_connector, target_connector,
                table_name, pk_columns, pk_start, pk_end,
                schema=schema, target_schema=target_schema,
                numeric_columns=numeric_columns,
            )
            results.append(r)
            logger.debug(
                "l3_chunk_validated",
                table=f"{schema}.{table_name}",
                pk_start=pk_start,
                pk_end=pk_end,
                status=r.status,
            )
        return results

    @staticmethod
    async def _query_source(
        connector: Any,
        schema: str,
        table: str,
        pk_columns: list[str],
        pk_start: Any,
        pk_end: Any,
        numeric_columns: list[str],
    ) -> dict[str, Any] | None:
        sum_cols = ", ".join(
            f"SUM(CAST([{c}] AS FLOAT)) AS sum_{c}" for c in numeric_columns
        )
        extra = f", {sum_cols}" if sum_cols else ""
        pk_col = pk_columns[0] if len(pk_columns) == 1 else None
        pk_bounds = f", MIN([{pk_col}]) AS min_pk, MAX([{pk_col}]) AS max_pk" if pk_col else ""

        if pk_start is None and pk_end is None:
            sql = (
                f"SELECT COUNT(*) AS cnt{pk_bounds}{extra} "
                f"FROM [{schema}].[{table}]"
            )
            params: dict[str, Any] | None = None
        elif pk_col is None:
            logger.warning(
                "l3_chunk_range_skipped_composite_pk",
                table=f"{schema}.{table}",
                pk_columns=pk_columns,
            )
            return None
        else:
            sql = (
                f"SELECT COUNT(*) AS cnt{pk_bounds}{extra} "
                f"FROM [{schema}].[{table}] "
                f"WHERE [{pk_col}] >= ? AND [{pk_col}] <= ?"
            )
            params = {"start": pk_start, "end": pk_end}
        try:
            rows = await connector.execute(sql, params) if params else await connector.execute(sql)
            return dict(rows[0]) if rows else None
        except Exception as exc:
            logger.error("l3_source_query_failed", error=str(exc))
            return None

    @staticmethod
    async def _query_target(
        connector: Any,
        target_schema: str,
        table: str,
        pk_columns: list[str],
        pk_start: Any,
        pk_end: Any,
        numeric_columns: list[str],
    ) -> dict[str, Any] | None:
        qualified = _pg_table_ref(target_schema, table)
        sum_cols = ", ".join(
            f'SUM(CAST({quote_pg_ident(c)} AS DOUBLE PRECISION)) AS "sum_{c}"'
            for c in numeric_columns
        )
        extra = f", {sum_cols}" if sum_cols else ""
        pk_col = pk_columns[0] if len(pk_columns) == 1 else None
        pk_bounds = (
            f", MIN({quote_pg_ident(pk_col)}) AS min_pk, "
            f"MAX({quote_pg_ident(pk_col)}) AS max_pk"
            if pk_col
            else ""
        )

        if pk_start is None and pk_end is None:
            sql = f"SELECT COUNT(*) AS cnt{pk_bounds}{extra} FROM {qualified}"
            params: tuple[Any, ...] | None = None
        elif pk_col is None:
            return None
        else:
            sql = (
                f"SELECT COUNT(*) AS cnt{pk_bounds}{extra} "
                f"FROM {qualified} "
                f"WHERE {quote_pg_ident(pk_col)} >= $1 AND {quote_pg_ident(pk_col)} <= $2"
            )
            params = (pk_start, pk_end)
        try:
            rows = await connector.execute(sql, *params) if params else await connector.execute(sql)
            return dict(rows[0]) if rows else None
        except Exception as exc:
            logger.error("l3_target_query_failed", error=str(exc))
            return None


# ---------------------------------------------------------------------------
# L4 — Statistical sampling
# ---------------------------------------------------------------------------

class L4StatisticalSamplingValidator:
    """Samples random rows from source and target and compares field-by-field.

    Uses a configurable sample size (default 1 % of rows, minimum 100 rows).
    For each sampled primary-key value the full row is fetched from both sides
    and compared.  Mismatches are recorded with the PK value and differing
    column details.

    Notes:
        - Sampling is non-deterministic; two runs may yield different samples.
        - Only columns present in *both* source and target are compared.
        - NULL equality: NULL == NULL is treated as matching (IS NOT DISTINCT FROM).
    """

    def __init__(self, sample_pct: float = 1.0, min_sample: int = 100) -> None:
        if not (0.0 < sample_pct <= 100.0):
            raise ValueError("sample_pct must be between 0 and 100")
        self._sample_pct = sample_pct
        self._min_sample = min_sample

    async def validate(
        self,
        source_connector: Any,
        target_connector: Any,
        table_name: str,
        pk_columns: list[str],
        schema: str = "dbo",
        target_schema: str = "public",
        row_count: int | None = None,
        *,
        source_database: str = "",
        column_type_overrides: dict[str, ResolvedColumnTypeOverride] | None = None,
    ) -> ValidationResult:
        """Run sampling validation on *table_name*."""
        result = ValidationResult(
            object_name=f"{schema}.{table_name}",
            category=ValidationCategory.QUERY_RESULT,
        )
        result.details["sample_pct"] = self._sample_pct
        result.details["pk_columns"] = pk_columns

        if not pk_columns:
            result.status = ValidationStatus.ERROR
            result.issues.append(
                ValidationIssue(
                    category=ValidationCategory.QUERY_RESULT,
                    severity="error",
                    message="No primary key columns found for sampling",
                )
            )
            return result

        total_rows = row_count or await self._count_source(
            source_connector, schema, table_name
        )
        n = max(self._min_sample, int(total_rows * self._sample_pct / 100))
        result.details["sample_n"] = n
        result.details["total_rows"] = total_rows

        logger.info(
            "l4_sampling_start",
            table=f"{schema}.{table_name}",
            sample_n=n,
            total_rows=total_rows,
            pk_columns=pk_columns,
        )

        pk_rows = await self._sample_source_pks(
            source_connector, schema, table_name, pk_columns, n
        )
        if pk_rows is None:
            result.status = ValidationStatus.ERROR
            result.issues.append(
                ValidationIssue(
                    category=ValidationCategory.QUERY_RESULT,
                    severity="error",
                    message="Sampling query failed on source",
                )
            )
            return result
        if not pk_rows:
            if total_rows == 0:
                result.status = ValidationStatus.SKIPPED
                result.details["reason"] = "empty_table"
                return result
            result.status = ValidationStatus.ERROR
            result.issues.append(
                ValidationIssue(
                    category=ValidationCategory.QUERY_RESULT,
                    severity="error",
                    message="No rows returned from source for sampling",
                )
            )
            return result

        mismatch_count = 0
        checked = 0
        for pk_values in pk_rows:
            if source_database:
                src_fetch = await fetch_source_row_safe(
                    source_connector,
                    schema,
                    table_name,
                    pk_columns,
                    pk_values,
                    database=source_database,
                    resolved_overrides=column_type_overrides,
                )
            else:
                src_fetch = await self._fetch_source_row(
                    source_connector, schema, table_name, pk_columns, pk_values,
                )
            src_row = src_fetch.row
            tgt_row = await self._fetch_target_row(
                target_connector, target_schema, table_name, pk_columns, pk_values
            )
            checked += 1
            pk_label = _pk_key_label(pk_columns, pk_values)

            if src_row is None and tgt_row is None and not src_fetch.fetch_error:
                continue

            if tgt_row is None:
                mismatch_count += 1
                result.issues.append(
                    ValidationIssue(
                        category=ValidationCategory.QUERY_RESULT,
                        severity="error",
                        message=f"Row with {pk_label} missing in target",
                        source_value=src_row,
                        target_value=None,
                        details={"pk_values": pk_values},
                    )
                )
                continue

            if src_fetch.fetch_error:
                mismatch_count += 1
                result.issues.append(
                    ValidationIssue(
                        category=ValidationCategory.QUERY_RESULT,
                        severity="error",
                        message=(
                            f"Row with {pk_label} could not be read from source: "
                            f"{src_fetch.fetch_error}"
                        ),
                        source_value=None,
                        target_value=tgt_row,
                        details={
                            "pk_values": pk_values,
                            "fetch_error": src_fetch.fetch_error,
                        },
                    )
                )
                continue

            if src_row is None:
                mismatch_count += 1
                result.issues.append(
                    ValidationIssue(
                        category=ValidationCategory.QUERY_RESULT,
                        severity="error",
                        message=f"Row with {pk_label} missing in source",
                        source_value=None,
                        target_value=tgt_row,
                        details={"pk_values": pk_values},
                    )
                )
                continue

            col_diffs = _compare_rows(src_row, tgt_row)
            if col_diffs:
                mismatch_count += 1
                result.issues.append(
                    ValidationIssue(
                        category=ValidationCategory.QUERY_RESULT,
                        severity="error",
                        message=(
                            f"Row {pk_label} has "
                            f"{len(col_diffs)} differing column(s): "
                            f"{', '.join(col_diffs)}"
                        ),
                        source_value=src_row,
                        target_value=tgt_row,
                        details={"pk_values": pk_values, "differing_columns": col_diffs},
                    )
                )

        result.details["checked"] = checked
        result.details["mismatches"] = mismatch_count
        result.source_count = checked
        result.target_count = checked - mismatch_count

        if mismatch_count == 0:
            result.status = ValidationStatus.PASSED
        else:
            result.status = ValidationStatus.FAILED

        logger.info(
            "l4_sampling_complete",
            table=f"{schema}.{table_name}",
            checked=checked,
            mismatches=mismatch_count,
            status=result.status,
        )
        return result

    @staticmethod
    async def _count_source(connector: Any, schema: str, table: str) -> int:
        from infrastructure.sqlserver.row_count_estimate import (
            fetch_sqlserver_table_row_estimate,
        )

        return await fetch_sqlserver_table_row_estimate(connector, schema, table)

    @staticmethod
    async def _sample_source_pks(
        connector: Any,
        schema: str,
        table: str,
        pk_columns: list[str],
        n: int,
    ) -> list[dict[str, Any]] | None:
        pk_cols_sql = ", ".join(f"[{c}]" for c in pk_columns)
        try:
            rows = await connector.execute(
                f"SELECT TOP {n} {pk_cols_sql} "
                f"FROM [{schema}].[{table}] ORDER BY NEWID()"
            )
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.error("l4_sample_pks_failed", error=str(exc))
            return None

    @staticmethod
    async def _fetch_source_row(
        connector: Any,
        schema: str,
        table: str,
        pk_columns: list[str],
        pk_values: dict[str, Any],
    ) -> SourceRowFetchResult:
        where = " AND ".join(f"[{c}] = ?" for c in pk_columns)
        params = {c: pk_values[c] for c in pk_columns}
        try:
            rows = await connector.execute(
                f"SELECT * FROM [{schema}].[{table}] WHERE {where}",
                params,
            )
            if rows:
                return SourceRowFetchResult(row=dict(rows[0]))
            return SourceRowFetchResult()
        except Exception as exc:
            logger.warning(
                "l4_fetch_source_row_failed",
                schema=schema,
                table=table,
                pk_values=pk_values,
                error=str(exc),
            )
            return SourceRowFetchResult(fetch_error=str(exc))

    @staticmethod
    async def _fetch_target_row(
        connector: Any,
        target_schema: str,
        table: str,
        pk_columns: list[str],
        pk_values: dict[str, Any],
    ) -> dict[str, Any] | None:
        qualified = _pg_table_ref(target_schema, table)
        where = " AND ".join(
            f"{quote_pg_ident(c)} = ${i}" for i, c in enumerate(pk_columns, 1)
        )
        params = tuple(pk_values[c] for c in pk_columns)
        try:
            rows = await connector.execute(
                f"SELECT * FROM {qualified} WHERE {where}",
                *params,
            )
            return dict(rows[0]) if rows else None
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _compare_rows(
    src: dict[str, Any], tgt: dict[str, Any]
) -> list[str]:
    """Return names of columns that differ between *src* and *tgt*.

    Comparison is case-insensitive on column names and uses NULL-safe equality
    (None == None is treated as equal).
    """
    src_lower = {k.lower(): v for k, v in src.items()}
    tgt_lower = {k.lower(): v for k, v in tgt.items()}
    common = set(src_lower) & set(tgt_lower)
    diffs: list[str] = []
    for col in sorted(common):
        sv = src_lower[col]
        tv = tgt_lower[col]
        if sv is None and tv is None:
            continue
        if sv != tv:
            try:
                if float(sv) == float(tv):  # type: ignore[arg-type]
                    continue
            except (TypeError, ValueError):
                pass
            diffs.append(col)
    return diffs
