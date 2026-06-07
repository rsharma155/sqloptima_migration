"""
Module: query_result_validator.py
Purpose: Query result validation and streaming comparison for source vs target
Author: Migration Platform Team
Created: 2026-05-22
Domain: Validation
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from domains.validation.validation_engine import (
    ValidationCategory,
    ValidationIssue,
    ValidationResult,
    ValidationStatus,
)


@dataclass
class QueryPair:
    """A source query and its target equivalent."""

    name: str
    source_query: str
    target_query: str
    parameters: dict[str, Any] | None = None


@dataclass
class StreamingComparisonConfig:
    """Configuration for streaming comparison."""

    chunk_size: int = 1000
    hash_algorithm: str = "sha256"
    max_rows_to_compare: int | None = None
    abort_on_first_mismatch: bool = True


@dataclass
class RowDiff:
    """A difference between a source and target row."""

    row_number: int
    key_values: dict[str, Any]
    differences: dict[str, tuple[Any, Any]]  # column -> (source_value, target_value)


@dataclass
class StreamingComparisonResult:
    """Result of a streaming comparison."""

    total_rows_compared: int = 0
    matching_rows: int = 0
    differing_rows: int = 0
    diffs: list[RowDiff] = field(default_factory=list)
    source_hash: str = ""
    target_hash: str = ""
    hashes_match: bool = False
    duration_seconds: float = 0.0
    success: bool = True
    error: str | None = None


class QueryResultValidator:
    """Validates by executing the same logical query on source and target."""

    async def validate(
        self,
        source_connector: Any,
        target_connector: Any,
        query_pair: QueryPair,
    ) -> ValidationResult:
        """Execute a query on both sides and compare results."""
        result = ValidationResult(
            object_name=query_pair.name,
            category=ValidationCategory.QUERY_RESULT,
        )
        start = datetime.now(UTC)

        try:
            source_rows = await source_connector.execute(
                query_pair.source_query, query_pair.parameters or {}
            )
            target_rows = await target_connector.execute(
                query_pair.target_query, query_pair.parameters or {}
            )
        except Exception as e:
            result.status = ValidationStatus.ERROR
            result.issues.append(ValidationIssue(
                category=ValidationCategory.QUERY_RESULT,
                severity="error",
                message=f"Query execution failed: {e}",
            ))
            return result

        result.source_count = len(source_rows)
        result.target_count = len(target_rows)

        if result.source_count != result.target_count:
            result.status = ValidationStatus.FAILED
            result.issues.append(ValidationIssue(
                category=ValidationCategory.QUERY_RESULT,
                severity="error",
                message=f"Row count mismatch: source={result.source_count}, target={result.target_count}",
            ))
            return result

        if not source_rows and not target_rows:
            result.status = ValidationStatus.PASSED
            return result

        source_cols = set(source_rows[0].keys()) if source_rows else set()
        target_cols = set(target_rows[0].keys()) if target_rows else set()

        if source_cols != target_cols:
            result.status = ValidationStatus.FAILED
            result.issues.append(ValidationIssue(
                category=ValidationCategory.QUERY_RESULT,
                severity="error",
                message=f"Column set mismatch: source={source_cols}, target={target_cols}",
            ))
            return result

        for i, (s_row, t_row) in enumerate(zip(source_rows, target_rows, strict=False)):
            for col in source_cols:
                s_val = str(s_row.get(col, ""))
                t_val = str(t_row.get(col, ""))
                if s_val != t_val:
                    result.status = ValidationStatus.FAILED
                    result.issues.append(ValidationIssue(
                        category=ValidationCategory.QUERY_RESULT,
                        severity="error",
                        message=f"Row {i}, column '{col}' mismatch",
                        source_value=s_val[:200],
                        target_value=t_val[:200],
                        details={"row": i, "column": col},
                    ))
                    if len(result.issues) >= 10:
                        break
            if len(result.issues) >= 10:
                break

        if not result.issues:
            result.status = ValidationStatus.PASSED

        result.duration_ms = (datetime.now(UTC) - start).total_seconds() * 1000
        return result


class StreamingComparator:
    """Compares large tables using streaming and hashing to minimize memory."""

    def __init__(self, config: StreamingComparisonConfig | None = None):
        self._config = config or StreamingComparisonConfig()

    async def compare_tables(
        self,
        source_connector: Any,
        target_connector: Any,
        source_schema: str,
        target_table: str,
        columns: list[str],
        key_column: str,
        source_table: str | None = None,
    ) -> StreamingComparisonResult:
        """Stream-compare two tables using chunked reads and hash comparison."""
        source_table = source_table or target_table
        result = StreamingComparisonResult()
        start = datetime.now(UTC)

        try:
            source_hash = hashlib.new(self._config.hash_algorithm)
            target_hash = hashlib.new(self._config.hash_algorithm)
            offset = 0
            total_compared = 0
            first_diff: RowDiff | None = None

            while True:
                if self._config.max_rows_to_compare and total_compared >= self._config.max_rows_to_compare:
                    break

                limit = self._config.chunk_size
                col_list = ", ".join(f'"{c}"' if c == key_column else f'"{c}"' for c in columns)
                source_col_list = ", ".join(f"[{c}]" for c in columns)

                source_rows = await source_connector.execute(
                    f"SELECT {source_col_list} FROM {source_schema}.{source_table} "
                    f"ORDER BY [{key_column}] "
                    f"OFFSET {offset} ROWS FETCH NEXT {limit} ROWS ONLY"
                )
                target_rows = await target_connector.execute(
                    f"SELECT {col_list} FROM \"{target_table}\" "
                    f"ORDER BY \"{key_column}\" "
                    f"LIMIT {limit} OFFSET {offset}"
                )

                if not source_rows and not target_rows:
                    break

                result.total_rows_compared += max(len(source_rows), len(target_rows))

                for s_row, t_row in zip(source_rows, target_rows, strict=False):
                    s_str = "|".join(str(s_row.get(c, "")) for c in columns)
                    t_str = "|".join(str(t_row.get(c, "")) for c in columns)
                    source_hash.update(s_str.encode())
                    target_hash.update(t_str.encode())

                    if s_str != t_str and first_diff is None:
                        diffs = {}
                        for c in columns:
                            sv = s_row.get(c)
                            tv = t_row.get(c)
                            if str(sv) != str(tv):
                                diffs[c] = (sv, tv)
                        first_diff = RowDiff(
                            row_number=total_compared,
                            key_values={key_column: s_row.get(key_column)},
                            differences=diffs,
                        )
                        result.diffs.append(first_diff)
                        if self._config.abort_on_first_mismatch:
                            result.differing_rows = 1
                            result.matching_rows = total_compared
                            result.success = False
                            break

                    total_compared += 1

                if self._config.abort_on_first_mismatch and result.diffs:
                    break

                offset += limit

            result.source_hash = source_hash.hexdigest()
            result.target_hash = target_hash.hexdigest()
            result.hashes_match = result.source_hash == result.target_hash

            if not result.diffs:
                result.matching_rows = total_compared
                result.success = True

        except Exception as e:
            result.success = False
            result.error = str(e)

        result.duration_seconds = (datetime.now(UTC) - start).total_seconds()
        return result
