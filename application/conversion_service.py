"""
Module: application/conversion_service.py
Purpose: Application service that orchestrates T-SQL → PL/pgSQL conversion.
         Wraps ProceduralConverter and provides a clean interface for routers
         that need per-request conversion without constructing domain objects.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from dataclasses import dataclass

from domains.transpilation.procedural_converter import (
    AppliedRepairInfo,
    ConversionResult,
    PostgresSyntaxIssue,
    ProceduralConverter,
)
from domains.transpilation.repair.conversion_repair_service import ConversionRepairService
from domains.validation.postgres_syntax_validator import PostgresSyntaxValidator
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)


@dataclass
class ConversionRequest:
    sql: str
    object_type: str = "auto"   # 'auto' | 'procedure' | 'function' | 'trigger' | 'raw'
    schema: str = "dbo"
    name: str = ""


class ConversionService:
    """Thin service wrapping :class:`ProceduralConverter`.

    Provides ``convert(req)`` as a single entry point so routers have no
    direct dependency on the domain class.

    Automatically enables Phase 1, 2, and 3 enhancement fixes:
    - Phase 1: Parameter formatting, variable prefixes, function mapping
    - Phase 2: Hint removal, pattern flagging
    - Phase 3: Transaction control, error handling, syntax cleanup

    After conversion, runs a validate → fix → re-validate repair loop (Phase A+B)
    to resolve common pgparse failures on PL/pgSQL output.

    Args:
        schema_mapper: Optional SchemaMapper for renaming source schemas to PostgreSQL equivalents.
        enable_phase_enhancements: Enable Phase 1, 2, and 3 enhancement fixes (default True).
        enable_repair: Run pgparse repair loop after conversion (default True).
    """

    def __init__(
        self,
        schema_mapper: "SchemaMapper | None" = None,
        enable_phase_enhancements: bool = True,
        validate_postgres_syntax: bool = True,
        enable_repair: bool = True,
    ) -> None:
        self._converter = ProceduralConverter(
            schema_mapper=schema_mapper,
            enable_phase_enhancements=enable_phase_enhancements,
        )
        self._validate_postgres_syntax = validate_postgres_syntax
        self._enable_repair = enable_repair
        self._postgres_validator = PostgresSyntaxValidator()
        self._repair_service = ConversionRepairService(self._postgres_validator)

    def convert(self, req: ConversionRequest) -> ConversionResult:
        """Convert *req.sql* to PL/pgSQL.

        Detects object type automatically when ``req.object_type == 'auto'``.
        """
        if not req.sql or not req.sql.strip():
            from domains.transpilation.procedural_converter import (
                ObjectType,
                ProceduralObject,
            )
            return self._finalize_pipeline_metadata(
                ConversionResult(
                    source=ProceduralObject(object_type=ObjectType.RAW),
                    success=False,
                    errors=["Empty SQL input"],
                )
            )

        if req.object_type == "auto":
            result = self._converter.auto_convert(req.sql)
        elif req.object_type == "procedure":
            result = self._converter.convert_procedure(
                req.schema, req.name or "usp_converted", [], req.sql
            )
        elif req.object_type == "function":
            result = self._converter.convert_function(
                req.schema, req.name or "ufn_converted", [], req.sql
            )
        elif req.object_type == "trigger":
            result = self._converter.convert_trigger(
                req.schema,
                req.name or "trg_converted",
                req.name or "target_table",
                "BEFORE",
                "INSERT OR UPDATE OR DELETE",
                req.sql,
            )
        else:
            result = self._converter.convert_adhoc(req.sql)

        if result.converted_sql and self._enable_repair:
            repair = self._repair_service.repair(result.converted_sql)
            result.converted_sql = repair.sql
            result.repairs_applied = [
                AppliedRepairInfo(
                    fixer=r.fixer,
                    description=r.description,
                    line=r.line,
                )
                for r in repair.repairs
            ]
            result.repair_exhausted = repair.repair_exhausted
            if repair.fixes_applied:
                result.warnings.append(
                    f"Auto-repaired {repair.fixes_applied} pgparse issue(s) in converted SQL"
                )

        if self._validate_postgres_syntax and result.converted_sql:
            result = self._apply_postgres_syntax_validation(result)

        result = self._finalize_pipeline_metadata(result)

        logger.info(
            "conversion_complete",
            object_type=req.object_type,
            success=result.success,
            warnings=len(result.warnings),
            postgres_syntax_valid=result.postgres_syntax_valid,
            repairs_applied=len(result.repairs_applied),
            parse_unblockers=len(result.parse_unblockers_applied),
            manual_review_required=result.manual_review_required,
        )
        return result

    @staticmethod
    def _finalize_pipeline_metadata(result: ConversionResult) -> ConversionResult:
        """Set manual-review flag after repair + validation complete."""
        result.manual_review_required = (
            not result.success
            or not result.postgres_syntax_valid
            or bool(result.errors)
            or result.body_transform_fallback
            or (result.repair_exhausted and not result.postgres_syntax_valid)
        )
        return result

    def _apply_postgres_syntax_validation(self, result: ConversionResult) -> ConversionResult:
        syntax = self._postgres_validator.validate(result.converted_sql)
        result.postgres_syntax_valid = syntax.valid
        result.postgres_syntax_errors = [
            PostgresSyntaxIssue(message=issue.message, line=issue.line, position=issue.position)
            for issue in syntax.errors
        ]
        result.postgres_syntax_warnings = list(syntax.warnings)
        if syntax.warnings:
            result.warnings.extend(syntax.warnings)
        if not syntax.valid:
            # Drop stale pgparse errors from a prior validation pass.
            result.errors = [
                e for e in result.errors if not e.startswith("PostgreSQL syntax:")
            ]
            for issue in syntax.errors:
                location = f" (line {issue.line})" if issue.line else ""
                result.errors.append(f"PostgreSQL syntax: {issue.message}{location}")
        return result
