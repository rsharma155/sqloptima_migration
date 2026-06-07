"""
Module: application/validation_service.py
Purpose: Orchestrates L1–L3 validation levels against a completed (or in-progress)
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

from domains.validation.l3_l4_validators import L3ChunkHashValidator
from domains.validation.validation_engine import (
    AggregateValidator,
    RowCountValidator,
    ValidationReport,
    ValidationResult,
    ValidationStatus,
)
from domains.validation.validation_report_exporter import (
    ValidationReportExporter,
    result_to_dict,
)
from infrastructure.metadata_db.repositories.validation_repository import (
    ValidationRepository,
)
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)

# Supported export formats
EXPORT_FORMATS = frozenset({"json", "csv", "html"})

_LEVEL_LABELS = {
    1: "L1 — Row Count",
    2: "L2 — Aggregates",
    3: "L3 — Chunk Validation",
}


class ValidationServiceError(Exception):
    pass


class ValidationService:
    """Orchestrates L1–L3 validation with full DB persistence.

    Levels:
    * 1 — row-count comparison (fast, sub-second per table)
    * 2 — aggregate comparison (MIN/MAX/SUM/AVG per numeric column)
    * 3 — per-chunk count + aggregate (``L3ChunkHashValidator``)

    Spot-check row samples are available separately via
    ``POST /api/v1/jobs/{job_id}/row-samples`` (default top 10 rows).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._repo = ValidationRepository(session)
        self._exporter = ValidationReportExporter()

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
    ) -> Any:
        if level not in (1, 2, 3):
            raise ValidationServiceError(
                f"Invalid level {level!r}; must be 1, 2, or 3"
            )

        run = await self._repo.create_run(job_id, level)
        await self._repo.start_run(run.validation_run_id)

        try:
            results = await self._execute_level(
                level, source_connector, target_connector,
                tables, chunks, pk_column,
            )
            report_obj = self._build_report(results, validation_level=level)
            report_dict = self._report_to_dict(report_obj)

            await self._persist_mismatches(run.validation_run_id, results, tables)
            await self._repo.complete_run(
                run.validation_run_id,
                report_obj.passed,
                report_obj.failed,
                report_dict,
            )
            logger.info(
                "validation_level_complete",
                job_id=job_id,
                level=level,
                passed=report_obj.passed,
                failed=report_obj.failed,
            )
        except Exception as exc:
            await self._repo.fail_run(run.validation_run_id, str(exc))
            logger.error(
                "validation_level_failed", job_id=job_id, level=level, error=str(exc),
            )
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
        levels = levels or [1, 2, 3]
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

    async def get_report(self, run_id: str, fmt: str) -> str:
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

    async def _execute_level(
        self,
        level: int,
        source_connector: Any,
        target_connector: Any,
        tables: list[dict[str, Any]],
        chunks: list[tuple[Any, Any]] | None,
        pk_column: str,
    ) -> list[ValidationResult]:
        from application.go_engine_migration.target_table_provisioner import _fetch_pk_columns

        async def _resolve_pk_columns(schema: str, table_name: str) -> list[str]:
            pk_cols = await _fetch_pk_columns(source_connector, schema, table_name)
            if pk_cols:
                return pk_cols
            if pk_column:
                return [pk_column]
            return ["id"]

        if level == 1:
            validator = RowCountValidator()
            results: list[ValidationResult] = []
            for tbl in tables:
                table_name = tbl.get("name", "")
                schema = tbl.get("schema", "dbo")
                target_schema = tbl.get("target_schema", "public")
                if not table_name:
                    continue
                results.append(
                    await validator.validate(
                        source_connector,
                        target_connector,
                        table_name,
                        schema,
                        target_schema=target_schema,
                    )
                )
            return results

        if level == 2:
            validator = AggregateValidator()
            results = []
            for tbl in tables:
                table_name = tbl.get("name", "")
                schema = tbl.get("schema", "dbo")
                target_schema = tbl.get("target_schema", "public")
                if not table_name:
                    continue
                results.append(
                    await validator.validate(
                        source_connector,
                        target_connector,
                        table_name,
                        schema,
                        target_schema=target_schema,
                    )
                )
            return results

        validator = L3ChunkHashValidator()
        results = []
        eff_chunks = chunks or []
        for tbl in tables:
            table_name = tbl.get("name", "")
            schema = tbl.get("schema", "dbo")
            target_schema = tbl.get("target_schema", "public")
            if not table_name:
                continue
            pk_columns = await _resolve_pk_columns(schema, table_name)
            if not eff_chunks:
                results.append(
                    await validator.validate_chunk(
                        source_connector,
                        target_connector,
                        table_name,
                        pk_columns,
                        None,
                        None,
                        schema=schema,
                        target_schema=target_schema,
                    )
                )
            else:
                results.extend(
                    await validator.validate_all_chunks(
                        source_connector,
                        target_connector,
                        table_name,
                        pk_columns,
                        eff_chunks,
                        schema=schema,
                        target_schema=target_schema,
                    )
                )
        return results

    @staticmethod
    def _build_report(
        results: list[ValidationResult],
        *,
        validation_level: int | None = None,
    ) -> ValidationReport:
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
            validation_level=validation_level,
        )
        if report.failed > 0:
            report.overall_status = ValidationStatus.FAILED
        elif report.warnings > 0:
            report.overall_status = ValidationStatus.WARNING
        return report

    @staticmethod
    def _report_to_dict(report: ValidationReport) -> dict:
        level = report.validation_level
        return {
            "overall_status": report.overall_status.value,
            "validation_level": level,
            "validation_level_label": _LEVEL_LABELS.get(level or 0, ""),
            "total_objects": report.total_objects,
            "passed": report.passed,
            "failed": report.failed,
            "warnings": report.warnings,
            "results": [result_to_dict(r) for r in report.results],
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
            if r.status not in (ValidationStatus.FAILED, ValidationStatus.ERROR):
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
                    "details": {
                        "message": issue.message,
                        "severity": issue.severity,
                        "category": issue.category.value,
                    },
                })
        if mismatches:
            await self._repo.bulk_record_mismatches(run_id, mismatches)

    @staticmethod
    def _run_to_report(run: Any) -> ValidationReport:
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
            issues = []
            for i in r.get("issues", []):
                try:
                    issue_cat = ValidationCategory(
                        i.get("category", cat.value),
                    )
                except ValueError:
                    issue_cat = cat
                issues.append(
                    ValidationIssue(
                        category=issue_cat,
                        severity=i.get("severity", "error"),
                        message=i.get("message", ""),
                        source_value=i.get("source_value"),
                        target_value=i.get("target_value"),
                        details=i.get("details") or {},
                    )
                )
            result_kwargs: dict[str, Any] = {
                "object_name": r.get("object_name", ""),
                "category": cat,
                "status": st,
                "source_count": r.get("source_count"),
                "target_count": r.get("target_count"),
                "duration_ms": float(r.get("duration_ms") or 0),
                "issues": issues,
                "details": r.get("details") or {},
            }
            raw_id = r.get("validation_id")
            if raw_id:
                from uuid import UUID

                try:
                    result_kwargs["validation_id"] = UUID(str(raw_id))
                except ValueError:
                    pass
            results.append(ValidationResult(**result_kwargs))

        try:
            overall = ValidationStatus(report_dict.get("overall_status", "passed"))
        except ValueError:
            overall = ValidationStatus.PASSED

        level = report_dict.get("validation_level")
        if level is not None:
            try:
                level = int(level)
            except (TypeError, ValueError):
                level = None

        return ValidationReport(
            results=results,
            total_objects=report_dict.get("total_objects", len(results)),
            passed=report_dict.get("passed", 0),
            failed=report_dict.get("failed", 0),
            warnings=report_dict.get("warnings", 0),
            overall_status=overall,
            validation_level=level,
        )
