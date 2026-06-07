"""
Module: domains/validation/row_hash_validator.py
Purpose: Cross-platform row hash comparison using MD5 on string-cast column values.
         Replaces the fundamentally incompatible ChecksumValidator (BINARY_CHECKSUM vs
         hashtext) with a meaningful, actionable validation tier.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)


@dataclass
class RowHashValidationResult:
    schema: str
    table: str
    sample_size: int
    rows_checked: int
    matching_rows: int
    mismatching_rows: int
    missing_in_target: int
    missing_in_source: int
    issues: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.mismatching_rows == 0 and self.missing_in_target == 0

    @property
    def match_rate_pct(self) -> float:
        if self.rows_checked == 0:
            return 100.0
        return (self.matching_rows / self.rows_checked) * 100.0


class RowHashValidator:
    """Validates row content by sampling N rows from source and target and comparing MD5 hashes.

    Uses a common algorithm (MD5 on CONCAT_WS('|', col1, col2, ...)) that works on
    both SQL Server and PostgreSQL, unlike the incompatible BINARY_CHECKSUM/hashtext approach.

    Fix 4.6: replaces ChecksumValidator which always returned WARNING due to
    fundamentally incompatible hash algorithms between SQL Server and PostgreSQL.
    """

    def __init__(self, sample_size: int = 1000) -> None:
        self._sample_size = sample_size

    async def validate(
        self,
        source_connector: Any,
        target_connector: Any,
        schema: str,
        table: str,
        pk_columns: list[str],
        data_columns: list[str] | None = None,
    ) -> RowHashValidationResult:
        result = RowHashValidationResult(
            schema=schema,
            table=table,
            sample_size=self._sample_size,
            rows_checked=0,
            matching_rows=0,
            mismatching_rows=0,
            missing_in_target=0,
            missing_in_source=0,
        )

        if not pk_columns:
            result.issues.append("No PK columns provided; cannot perform row hash validation.")
            return result

        # Sample PKs from source
        pk_col_list = ", ".join(f"[{c}]" for c in pk_columns)
        pk_col_pg_list = ", ".join(f'"{c}"' for c in pk_columns)

        try:
            src_rows = await source_connector.execute(
                f"SELECT TOP {self._sample_size} {pk_col_list} "
                f"FROM [{schema}].[{table}] ORDER BY NEWID()"
            )
        except Exception as exc:
            result.issues.append(f"Source sample query failed: {exc}")
            return result

        if not src_rows:
            return result

        # Build source hashes using MD5 on all columns
        try:
            src_hashes = await self._fetch_source_hashes(
                source_connector, schema, table, pk_columns, src_rows, data_columns
            )
        except Exception as exc:
            result.issues.append(f"Source hash query failed: {exc}")
            return result

        # Fetch matching rows from target
        try:
            tgt_hashes = await self._fetch_target_hashes(
                target_connector, schema, table, pk_columns, src_rows, data_columns
            )
        except Exception as exc:
            result.issues.append(f"Target hash query failed: {exc}")
            return result

        result.rows_checked = len(src_hashes)
        for pk_key, src_hash in src_hashes.items():
            if pk_key not in tgt_hashes:
                result.missing_in_target += 1
                result.issues.append(f"Row {pk_key} missing in target.")
            elif src_hash == tgt_hashes[pk_key]:
                result.matching_rows += 1
            else:
                result.mismatching_rows += 1
                result.issues.append(f"Row {pk_key} hash mismatch: source={src_hash[:8]}… target={tgt_hashes[pk_key][:8]}…")

        for pk_key in tgt_hashes:
            if pk_key not in src_hashes:
                result.missing_in_source += 1

        logger.info(
            "Row hash validation complete",
            table=f"{schema}.{table}",
            rows_checked=result.rows_checked,
            matching=result.matching_rows,
            mismatching=result.mismatching_rows,
            match_rate=f"{result.match_rate_pct:.1f}%",
        )
        return result

    async def _fetch_source_hashes(
        self, connector: Any, schema: str, table: str,
        pk_columns: list[str], sample_rows: list[dict], data_columns: list[str] | None
    ) -> dict[str, str]:
        if not sample_rows:
            return {}
        pk_vals = [tuple(r[c] for c in pk_columns) for r in sample_rows]
        in_clause = ", ".join(f"({', '.join('?' for _ in pk_columns)})" for _ in pk_vals)
        flat_params = [v for row in pk_vals for v in row]

        col_str = "*" if not data_columns else ", ".join(f"[{c}]" for c in data_columns)
        pk_col_str = ", ".join(f"[{c}]" for c in pk_columns)

        # SQL Server MD5: CONVERT(NVARCHAR(32), HASHBYTES('MD5', CONCAT_WS('|', ...)), 2)
        all_cols = list(pk_columns) + (data_columns or [])
        concat_expr = ", '|', ".join(f"CAST([{c}] AS NVARCHAR(MAX))" for c in all_cols)
        hash_expr = f"CONVERT(NVARCHAR(32), HASHBYTES('MD5', CONCAT({concat_expr})), 2)"

        query = (
            f"SELECT {pk_col_str}, {hash_expr} AS row_hash "
            f"FROM [{schema}].[{table}] "
            f"WHERE ({pk_col_str}) IN ({in_clause})"
        )
        rows = await connector.execute(query, {str(i): v for i, v in enumerate(flat_params)})
        return {
            "|".join(str(r[c]) for c in pk_columns): r.get("row_hash", "") or ""
            for r in rows
        }

    async def _fetch_target_hashes(
        self, connector: Any, schema: str, table: str,
        pk_columns: list[str], sample_rows: list[dict], data_columns: list[str] | None
    ) -> dict[str, str]:
        if not sample_rows:
            return {}
        all_cols = list(pk_columns) + (data_columns or [])
        concat_expr = " || '|' || ".join(f'COALESCE({c}::TEXT, \'\')' for c in all_cols)
        hash_expr = f"MD5({concat_expr})"

        # Build WHERE pk IN (...)
        pk_col_pg = ", ".join(f'"{c}"' for c in pk_columns)
        pk_vals = [tuple(r[c] for c in pk_columns) for r in sample_rows]
        in_clause = ", ".join("(" + ", ".join("$" + str(i * len(pk_columns) + j + 1) for j in range(len(pk_columns))) + ")" for i, _ in enumerate(pk_vals))
        flat_params = [v for row in pk_vals for v in row]

        query = (
            f'SELECT {pk_col_pg}, {hash_expr} AS row_hash '
            f'FROM "{schema}"."{table}" '
            f'WHERE ({pk_col_pg}) IN ({in_clause})'
        )
        rows = await connector.execute(query, *flat_params)
        return {
            "|".join(str(r[c]) for c in pk_columns): r.get("row_hash", "") or ""
            for r in rows
        }
