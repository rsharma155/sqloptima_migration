"""
Module: domains/validation/sample_validator.py
Purpose: Fix F.6 — SampleValidator provides a quick "sanity check" validation
         tier that compares a small random sample of rows (default 100) between
         source and target using column-by-column equality after type coercion.
         Intended as a fast first-pass check; RowHashValidator is the full audit.
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
class SampleMismatch:
    pk_key: str
    column_name: str
    source_value: Any
    target_value: Any


@dataclass
class SampleValidationResult:
    schema: str
    table: str
    rows_sampled: int
    rows_matched: int
    mismatches: list[SampleMismatch] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.mismatches and not self.errors

    @property
    def mismatch_rate_pct(self) -> float:
        if self.rows_sampled == 0:
            return 0.0
        return (len(self.mismatches) / self.rows_sampled) * 100.0


class SampleValidator:
    """Validates a random sample of rows between source (SQL Server) and target (PostgreSQL).

    Fix F.6: provides a lightweight validation alternative to RowHashValidator —
    it fetches full rows (not hashes) so mismatches show which column differs.
    Useful for debugging; RowHashValidator is faster for large tables.
    """

    def __init__(self, sample_size: int = 100) -> None:
        self._sample_size = sample_size

    async def validate(
        self,
        source_connector: Any,
        target_connector: Any,
        schema: str,
        table: str,
        pk_columns: list[str],
        data_columns: list[str],
    ) -> SampleValidationResult:
        result = SampleValidationResult(
            schema=schema,
            table=table,
            rows_sampled=0,
            rows_matched=0,
        )

        if not pk_columns:
            result.errors.append("No PK columns specified; cannot perform sample validation.")
            return result

        pk_col_src = ", ".join(f"[{c}]" for c in pk_columns)
        all_src_cols = ", ".join(f"[{c}]" for c in pk_columns + data_columns)

        # Sample from source
        try:
            src_rows = await source_connector.execute(
                f"SELECT TOP {self._sample_size} {all_src_cols} "
                f"FROM [{schema}].[{table}] ORDER BY NEWID()"
            )
        except Exception as exc:
            result.errors.append(f"Source sample failed: {exc}")
            return result

        if not src_rows:
            return result

        result.rows_sampled = len(src_rows)

        # Build pk-keyed source map
        src_map: dict[str, dict[str, Any]] = {
            "|".join(str(r[c]) for c in pk_columns): r
            for r in src_rows
        }

        # Fetch matching rows from target
        pk_col_pg = ", ".join(f'"{c}"' for c in pk_columns)
        all_tgt_cols = ", ".join(f'"{c}"' for c in pk_columns + data_columns)
        pk_vals = [tuple(r[c] for c in pk_columns) for r in src_rows]
        in_clause = ", ".join(
            "(" + ", ".join("$" + str(i * len(pk_columns) + j + 1) for j in range(len(pk_columns))) + ")"
            for i, _ in enumerate(pk_vals)
        )
        flat_params = [v for row in pk_vals for v in row]

        try:
            tgt_rows = await target_connector.execute(
                f'SELECT {all_tgt_cols} FROM "{schema}"."{table}" '
                f'WHERE ({pk_col_pg}) IN ({in_clause})',
                *flat_params,
            )
        except Exception as exc:
            result.errors.append(f"Target fetch failed: {exc}")
            return result

        tgt_map: dict[str, dict[str, Any]] = {
            "|".join(str(r[c]) for c in pk_columns): r
            for r in tgt_rows
        }

        for pk_key, src_row in src_map.items():
            if pk_key not in tgt_map:
                result.mismatches.append(SampleMismatch(
                    pk_key=pk_key,
                    column_name="<row>",
                    source_value="exists",
                    target_value="<missing>",
                ))
                continue

            tgt_row = tgt_map[pk_key]
            row_matches = True
            for col in data_columns:
                sv = _coerce(src_row.get(col))
                tv = _coerce(tgt_row.get(col))
                if sv != tv:
                    result.mismatches.append(SampleMismatch(
                        pk_key=pk_key,
                        column_name=col,
                        source_value=sv,
                        target_value=tv,
                    ))
                    row_matches = False

            if row_matches:
                result.rows_matched += 1

        logger.info(
            "sample_validation_complete",
            table=f"{schema}.{table}",
            rows_sampled=result.rows_sampled,
            rows_matched=result.rows_matched,
            mismatches=len(result.mismatches),
        )
        return result


def _coerce(value: Any) -> Any:
    """Normalize values for cross-platform comparison (e.g. Decimal → float, bytes → hex str)."""
    if value is None:
        return None
    from decimal import Decimal
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    return value
