"""
Module: application/validation_service.py
Purpose: Orchestrates L1–L4 validation levels against a completed (or in-progress)
         migration job.  Each invocation creates a ValidationRunRecord, runs the
         requested level, persists per-table mismatches, and marks the run
         COMPLETED or FAILED.  Report export (JSON/CSV/HTML) is provided via
         get_report().
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from domains.validation.l3_l4_validators import (
    L3ChunkHashValidator,
    L4StatisticalSamplingValidator,
)
from domains.validation.validation_engine import (
    AggregateValidator,
    RowCountValidator,
    ValidationEngine,
    ValidationReport,
    ValidationResult,
    ValidationStatus,
)
from domains.validation.validation_report_exporter import ValidationReportExporter
from infrastructure.metadata_db.repositories.validation_repository import (
    ValidationRepository,
)
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)

# Supported export formats
EXPORT_FORMATS = frozenset({"json", "csv", "html"})


class ValidationServiceError(Exception):
    pass


class ValidationService:
    """Orchestrates L1–L4 validation with full DB persistence.

    Levels:
    * 1 — row-count comparison (fast, sub-second per table)
    * 2 — aggregate comparison (MIN/MAX/SUM per numeric column)
    * 3 — per-chunk count + aggregate (``L3ChunkHashValidator``)
    * 4 — statistical random sampling (``L4StatisticalSamplingValidator``)

    Usage::

        svc = ValidationService(session)
        run = await svc.run_level(
            job_id=job_id, level=1,
            source_connector=src, target_connector=tgt,
            tables=[{"name": "orders", "schema": "dbo"}],
        )
        report_json = await svc.get_report(run.validation_run_id, "json")
    """

    def __init__(self, session: AsyncSession) -> None:
        self._repo = ValidationRepository(session)
        self._exporter = ValidationReportExporter()

    # ------------------------------------------------------------------
    # Validation execution
    # ------------------------------------------------------------------

    async def run_level(
        self,
        job_id: str,
        level: int,
        source_connector: Any,
        target_connector: Any,
        tables: list[dict[str, Any]],
        chunks: list[tuple[Any, Any]] | None = None,
        pk_column: str = "id",
        sample_pct: float = 1.0,
    ) -> Any:  # returns ValidationRunRecord
        """Run a single validation level and persist results.

        Args:
            job_id: Parent migration job UUID.
            level: 1–4.
            source_connector: Connector with async ``execute(sql, params)`` method.
            target_connector: Connector with async ``execute(sql, params)`` method.
            tables: ``[{"name": "orders", "schema": "dbo", "source_columns": [...]}]``
            chunks: Required for level 3 — list of ``(pk_start, pk_end)`` tuples.
            pk_column: PK column name used for L3/L4 chunking/sampling.
            sample_pct: Sampling percentage for level 4 (0 < pct ≤ 100).

        Returns:
            Persisted :class:`ValidationRunRecord`.
        """
        if level not in (1, 2, 3, 4):
            raise ValidationServiceError(
                f"Invalid level {level!r}; must be 1, 2, 3, or 4"
            )

        run = await self._repo.create_run(job_id, level)
        await self._repo.start_run(run.validation_run_id)

        try:
            results = await self._execute_level(
                level, source_connector, target_connector,
                tables, chunks, pk_column, sample_pct,
            )
            report_obj = self._build_report(results)
            pass_count = report_obj.passed
            fail_count = report_obj.failed
            report_dict = self._report_to_dict(report_obj)

            await self._persist_mismatches(run.validation_run_id, results, tables)
            await self._repo.complete_run(run.validation_run_id, pass_count, fail_count, report_dict)
            logger.info(
                "validation_level_complete",
                job_id=job_id,
                level=level,
                passed=pass_count,
                failed=fail_count,
            )
        except Exception as exc:
            await self._repo.fail_run(run.validation_run_id, str(exc))
            logger.error("validation_level_failed", job_id=job_id, level=level, error=str(exc))
            raise

        return await self._repo.get_run(run.validation_run_id)

    async def run_all_levels(
        self,
        job_id: str,
        source_connector: Any,
        target_connector: Any,
        tables: list[dict[str, Any]],
        levels: list[int] | None = None,
        chunks: list[tuple[Any, Any]] | None = None,
        pk_column: str = "id",
        sample_pct: float = 1.0,
    ) -> list[Any]:
        """Run multiple validation levels sequentially."""
        levels = levels or [1, 2, 3, 4]
        runs = []
        for lvl in levels:
            run = await self.run_level(
                job_id=job_id,
                level=lvl,
                source_connector=source_connector,
                target_connector=target_connector,
                tables=tables,
                chunks=chunks,
                pk_column=pk_column,
                sample_pct=sample_pct,
            )
            runs.append(run)
        return runs

    # ------------------------------------------------------------------
    # Report export
    # ------------------------------------------------------------------

    async def get_report(self, run_id: str, fmt: str) -> str:
        """Return the validation report for *run_id* in *fmt* (json/csv/html)."""
        fmt = fmt.lower()
        if fmt not in EXPORT_FORMATS:
            raise ValidationServiceError(
                f"Unsupported format {fmt!r}; must be one of {sorted(EXPORT_FORMATS)}"
            )
        run = await self._repo.get_run(run_id)
        if run is None:
            raise ValidationServiceError(f"Validation run {run_id!r} not found")

        report_obj = self._run_to_report(run)

        if fmt == "json":
            return self._exporter.to_json(report_obj)
        if fmt == "csv":
            return self._exporter.to_csv(report_obj)
        return self._exporter.to_html(report_obj)

    async def list_runs(self, job_id: str) -> list[Any]:
        return await self._repo.get_runs_for_job(job_id)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _execute_level(
        self,
        level: int,
        source_connector: Any,
        target_connector: Any,
        tables: list[dict[str, Any]],
        chunks: list[tuple[Any, Any]] | None,
        pk_column: str,
        sample_pct: float,
    ) -> list[ValidationResult]:
        if level == 1:
            engine = ValidationEngine(row_count_validator=RowCountValidator())
            report = await engine.validate_migration(
                source_connector, target_connector, tables
            )
            return [r for r in report.results if r.category.value == "row_count"]

        if level == 2:
            engine = ValidationEngine(
                aggregate_validator=AggregateValidator(),
            )
            report = await engine.validate_migration(
                source_connector, target_connector, tables, run_aggregate_validation=True
            )
            return [
                r for r in report.results
                if isinstance(getattr(r, "details", None), dict)
                and r.details.get("aggregate_functions")
            ]

        if level == 3:
            validator = L3ChunkHashValidator()
            results: list[ValidationResult] = []
            eff_chunks = chunks or []
            for tbl in tables:
                table_name = tbl.get("name", "")
                schema = tbl.get("schema", "dbo")
                if not eff_chunks:
                    # No chunks provided: fall back to single full-table range
                    r = await validator.validate_chunk(
                        source_connector, target_connector,
                        table_name, pk_column, None, None, schema=schema,
                    )
                    results.append(r)
                else:
                    chunk_results = await validator.validate_all_chunks(
                        source_connector, target_connector,
                        table_name, pk_column, eff_chunks, schema=schema,
                    )
                    results.extend(chunk_results)
            return results

        # level == 4
        validator_l4 = L4StatisticalSamplingValidator(sample_pct=sample_pct)
        results = []
        for tbl in tables:
            table_name = tbl.get("name", "")
            schema = tbl.get("schema", "dbo")
            r = await validator_l4.validate(
                source_connector, target_connector,
                table_name, pk_column, schema=schema,
            )
            results.append(r)
        return results

    @staticmethod
    def _build_report(results: list[ValidationResult]) -> ValidationReport:
        report = ValidationReport(
            results=results,
            total_objects=len(results),
            passed=sum(1 for r in results if r.status == ValidationStatus.PASSED),
            failed=sum(
                1 for r in results
                if r.status in (ValidationStatus.FAILED, ValidationStatus.ERROR)
            ),
            warnings=sum(
                1 for r in results
                if r.status in (ValidationStatus.WARNING, ValidationStatus.SKIPPED)
            ),
        )
        if report.failed > 0:
            report.overall_status = ValidationStatus.FAILED
        elif report.warnings > 0:
            report.overall_status = ValidationStatus.WARNING
        return report

    @staticmethod
    def _report_to_dict(report: ValidationReport) -> dict:
        return {
            "overall_status": report.overall_status.value,
            "total_objects": report.total_objects,
            "passed": report.passed,
            "failed": report.failed,
            "warnings": report.warnings,
            "results": [
                {
                    "object_name": r.object_name,
                    "category": r.category.value,
                    "status": r.status.value,
                    "source_count": r.source_count,
                    "target_count": r.target_count,
                    "issues": [
                        {"severity": i.severity, "message": i.message}
                        for i in r.issues
                    ],
                }
                for r in report.results
            ],
        }

    async def _persist_mismatches(
        self,
        run_id: str,
        results: list[ValidationResult],
        tables: list[dict[str, Any]],
    ) -> None:
        table_lookup = {t.get("name", ""): t.get("schema", "dbo") for t in tables}
        mismatches = []
        for r in results:
            if r.status != ValidationStatus.FAILED:
                continue
            table_name = r.object_name.split(".")[-1].split("[")[0].strip()
            schema = table_lookup.get(table_name, "")
            for issue in r.issues:
                mismatches.append({
                    "table_schema": schema,
                    "table_name": table_name,
                    "mismatch_type": r.category.value.upper(),
                    "source_value": issue.source_value,
                    "target_value": issue.target_value,
                    "details": {"message": issue.message, "severity": issue.severity},
                })
        if mismatches:
            await self._repo.bulk_record_mismatches(run_id, mismatches)

    @staticmethod
    def _run_to_report(run: Any) -> ValidationReport:
        """Reconstruct a ValidationReport from a stored run's JSON report dict."""

        from domains.validation.validation_engine import (
            ValidationCategory,
            ValidationIssue,
        )

        report_dict = run.report or {}
        results: list[ValidationResult] = []
        for r in report_dict.get("results", []):
            try:
                cat = ValidationCategory(r.get("category", "row_count"))
            except ValueError:
                cat = ValidationCategory.ROW_COUNT
            try:
                st = ValidationStatus(r.get("status", "passed"))
            except ValueError:
                st = ValidationStatus.PASSED
            issues = [
                ValidationIssue(
                    category=cat,
                    severity=i.get("severity", "error"),
                    message=i.get("message", ""),
                )
                for i in r.get("issues", [])
            ]
            results.append(ValidationResult(
                object_name=r.get("object_name", ""),
                category=cat,
                status=st,
                source_count=r.get("source_count"),
                target_count=r.get("target_count"),
                issues=issues,
            ))

        try:
            overall = ValidationStatus(report_dict.get("overall_status", "passed"))
        except ValueError:
            overall = ValidationStatus.PASSED

        return ValidationReport(
            results=results,
            total_objects=report_dict.get("total_objects", len(results)),
            passed=report_dict.get("passed", 0),
            failed=report_dict.get("failed", 0),
            warnings=report_dict.get("warnings", 0),
            overall_status=overall,
        )
