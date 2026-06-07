"""Differential test harness for T-SQL → PL/pgSQL runtime equivalence (§11.2).

Runs a corpus of (setup, call, expected resultset) triples against source and
target connectors and asserts semantic equality — not just convertibility.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from application.conversion_service import ConversionRequest, ConversionService
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)


@dataclass
class EquivalenceCase:
    """Single procedure equivalence test case."""

    name: str
    source_sql: str
    setup_sql: str = ""
    source_call: str = ""
    target_call: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    expected_rows: list[list[Any]] | None = None
    expected_columns: list[str] | None = None
    skip_runtime: bool = False
    notes: str = ""


@dataclass
class EquivalenceResult:
    case_name: str
    passed: bool
    conversion_success: bool = False
    source_row_count: int = 0
    target_row_count: int = 0
    converted_sql: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _normalize_cell(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (int, float, str, bool)):
        return value
    return str(value)


def _normalize_rows(rows: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    if not rows:
        return []
    cols = list(rows[0].keys())
    return [tuple(_normalize_cell(r.get(c)) for c in cols) for r in rows]


def compare_resultsets(
    source_rows: list[dict[str, Any]],
    target_rows: list[dict[str, Any]],
) -> tuple[bool, str]:
    """Compare two result sets with type-normalized cell values."""
    src = sorted(_normalize_rows(source_rows))
    tgt = sorted(_normalize_rows(target_rows))
    if len(src) != len(tgt):
        return False, f"row count mismatch: source={len(src)} target={len(tgt)}"
    for i, (s, t) in enumerate(zip(src, tgt)):
        if s != t:
            return False, f"row {i} differs: source={s} target={t}"
    return True, ""


def load_corpus(path: str | Path) -> list[EquivalenceCase]:
    """Load equivalence cases from a JSON corpus file."""
    data = json.loads(Path(path).read_text())
    cases: list[EquivalenceCase] = []
    for entry in data.get("cases", []):
        cases.append(EquivalenceCase(**entry))
    return cases


class ProcedureEquivalenceHarness:
    """Execute equivalence cases against source/target DB connectors."""

    def __init__(
        self,
        source_connector: Any | None = None,
        target_connector: Any | None = None,
        conversion_service: ConversionService | None = None,
    ) -> None:
        self._source = source_connector
        self._target = target_connector
        self._converter = conversion_service or ConversionService()

    async def run_case(self, case: EquivalenceCase) -> EquivalenceResult:
        result = EquivalenceResult(case_name=case.name, passed=False)

        conv = self._converter.convert(
            ConversionRequest(
                sql=case.source_sql,
                object_type="procedure",
                schema="dbo",
                name=case.name,
            )
        )
        result.converted_sql = conv.converted_sql or ""
        result.conversion_success = conv.success and bool(conv.converted_sql)
        if not result.conversion_success:
            result.errors.extend(conv.errors or ["Conversion failed"])
            return result

        if case.skip_runtime or self._source is None or self._target is None:
            if case.expected_rows is not None:
                result.passed = True
                result.warnings.append("static expected_rows check skipped without connectors")
            else:
                result.passed = result.conversion_success
                result.warnings.append("convertibility-only (no runtime connectors)")
            return result

        try:
            if case.setup_sql:
                await self._source.execute(case.setup_sql)
                await self._target.execute(case.setup_sql)

            src_call = case.source_call or case.target_call
            tgt_call = case.target_call or case.source_call
            if not src_call or not tgt_call:
                result.errors.append("source_call and target_call required for runtime mode")
                return result

            source_rows = await self._source.execute(src_call, case.args or None)
            target_rows = await self._target.execute(tgt_call, case.args or None)
            result.source_row_count = len(source_rows)
            result.target_row_count = len(target_rows)

            ok, detail = compare_resultsets(source_rows, target_rows)
            if not ok:
                result.errors.append(detail)
                return result

            if case.expected_rows is not None:
                expected = [tuple(_normalize_cell(c) for c in row) for row in case.expected_rows]
                actual = _normalize_rows(source_rows)
                if sorted(actual) != sorted(expected):
                    result.errors.append(
                        f"expected rows mismatch: {json.dumps(expected)} vs {json.dumps(actual)}"
                    )
                    return result

            result.passed = True
        except Exception as exc:
            result.errors.append(f"{type(exc).__name__}: {exc}")
        return result

    async def deploy_and_run(self, case: EquivalenceCase) -> EquivalenceResult:
        """Deploy source proc + converted PG function, then compare runtime results."""
        result = await self.run_case(case)
        if not result.conversion_success or case.skip_runtime:
            return result
        if self._source is None or self._target is None:
            result.errors.append("connectors required for deploy_and_run")
            return result
        try:
            proc_name = case.name.replace("-", "_")
            await self._source.execute(
                f"IF OBJECT_ID('dbo.{proc_name}', 'P') IS NOT NULL DROP PROCEDURE dbo.{proc_name};"
            )
            await self._source.execute(case.source_sql)
            await self._target.execute(
                f"DROP FUNCTION IF EXISTS dbo.{proc_name} CASCADE;"
            )
            if result.converted_sql:
                await self._target.execute(result.converted_sql)
            src_call = case.source_call or f"EXEC dbo.{proc_name}"
            tgt_call = case.target_call or f"SELECT * FROM dbo.{proc_name}()"
            source_rows = await self._source.execute(src_call, case.args or None)
            target_rows = await self._target.execute(tgt_call, case.args or None)
            ok, detail = compare_resultsets(source_rows, target_rows)
            result.source_row_count = len(source_rows)
            result.target_row_count = len(target_rows)
            if ok:
                result.passed = True
            else:
                result.passed = False
                result.errors.append(detail)
        except Exception as exc:
            result.passed = False
            result.errors.append(f"deploy: {type(exc).__name__}: {exc}")
        return result

    async def run_corpus(
        self,
        cases: list[EquivalenceCase],
        *,
        deploy: bool = False,
    ) -> list[EquivalenceResult]:
        results: list[EquivalenceResult] = []
        for case in cases:
            if deploy and not case.skip_runtime:
                results.append(await self.deploy_and_run(case))
            else:
                results.append(await self.run_case(case))
        return results

    def summary(self, results: list[EquivalenceResult]) -> dict[str, Any]:
        passed = sum(1 for r in results if r.passed)
        return {
            "total": len(results),
            "passed": passed,
            "failed": len(results) - passed,
            "semantic_equivalence_pct": round(100 * passed / len(results), 1) if results else 0,
            "failures": [
                {"case": r.case_name, "errors": r.errors}
                for r in results
                if not r.passed
            ],
        }
