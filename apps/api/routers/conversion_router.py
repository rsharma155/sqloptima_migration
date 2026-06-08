# Author: Ravi Sharma
# Copyright (c) 2026 Ravi Sharma
# SPDX-License-Identifier: MIT

"""SQL conversion routes — T-SQL → PL/pgSQL and syntax validation."""

from __future__ import annotations

import asyncio
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from apps.api.middleware.auth import UserRole, require_role
from application.conversion_service import ConversionRequest
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["conversion"])

# Object types accepted by ConversionService; anything else is a client error.
_ALLOWED_OBJECT_TYPES = frozenset({"auto", "procedure", "function", "trigger", "raw"})

_TRIGGER_TIMING_RE = re.compile(
    r"\b(INSTEAD\s+OF|AFTER|FOR)\s+"
    r"((?:INSERT|UPDATE|DELETE)(?:\s*,\s*(?:INSERT|UPDATE|DELETE))*)",
    re.IGNORECASE,
)


def _parse_trigger_metadata(sql: str) -> tuple[str | None, str | None]:
    """Parse trigger timing and events from CREATE TRIGGER statement.

    Returns (timing, events) where timing is 'BEFORE', 'AFTER', or 'INSTEAD OF'.
    Returns (None, None) if trigger metadata cannot be determined.
    Explicitly fails rather than defaulting (UX-01).
    """
    match = _TRIGGER_TIMING_RE.search(sql)
    if match:
        raw = re.sub(r"\s+", " ", match.group(1).strip().upper())
        timing = "INSTEAD OF" if raw == "INSTEAD OF" else "AFTER"
        events = [e.strip().upper() for e in match.group(2).split(",")]
        return timing, " OR ".join(events)
    return None, None


# ---- Models ----

class ConvertRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    sql: str = Field(..., max_length=1_000_000)
    object_type: str = "auto"
    object_name: str = "usp_example"
    schema_name: str = Field(default="dbo", alias="schema")
    parameters: list[dict] = []
    # Optional schema mapping: {"dbo": "public", "hr": "staff"}
    schema_mapping: dict[str, str] | None = None
    # map_to_public (default) or preserve_dbo — keep dbo schema on PostgreSQL
    dbo_schema_strategy: str = "map_to_public"


class PostgresSyntaxIssueResponse(BaseModel):
    message: str
    line: int | None = None
    position: int | None = None


class AppliedRepairResponse(BaseModel):
    fixer: str
    description: str
    line: int | None = None


class ConvertResponse(BaseModel):
    converted_sql: str = ""
    success: bool = False
    warnings: list[str] = []
    errors: list[str] = []
    postgres_syntax_valid: bool = True
    postgres_syntax_errors: list[PostgresSyntaxIssueResponse] = []
    postgres_syntax_warnings: list[str] = []
    repairs_applied: list[AppliedRepairResponse] = []
    repair_exhausted: bool = False
    parse_unblockers_applied: list[str] = []
    body_transform_fallback: bool = False
    manual_review_required: bool = False


# ---- Endpoints ----

@router.post("/convert", response_model=ConvertResponse)
async def convert_sql(req: ConvertRequest, _: dict = require_role(UserRole.OPERATOR)):
    """Convert T-SQL to PL/pgSQL with schema mapping and async execution.

    Delegates to ConversionService (application layer) to maintain clean architecture.
    Large conversions are offloaded to executor to prevent event loop blocking.
    """
    from application.conversion_factory import build_conversion_service
    from shared.kernel.ddl_identifier import validate_sql_identifier

    # Reject unknown object types explicitly rather than silently treating them
    # as ad-hoc SQL.
    if req.object_type not in _ALLOWED_OBJECT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid object_type {req.object_type!r}. "
                f"Allowed: {', '.join(sorted(_ALLOWED_OBJECT_TYPES))}."
            ),
        )

    # Validate identifier inputs (ARCH-02: ID validation)
    try:
        validate_sql_identifier(req.schema_name, "schema")
        validate_sql_identifier(req.object_name, "object_name")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Setup schema mapping — shared with procedural migration service
    if req.schema_mapping is not None:
        service = build_conversion_service(
            req.schema_name,
            schema_mapping=req.schema_mapping,
            dbo_schema_strategy=req.dbo_schema_strategy,
        )
    else:
        target = "dbo" if req.dbo_schema_strategy == "preserve_dbo" else None
        service = build_conversion_service(
            req.schema_name,
            target,
            dbo_schema_strategy=req.dbo_schema_strategy,
        )

    if req.object_type == "trigger":
        timing, events = _parse_trigger_metadata(req.sql)
        if timing is None:
            raise HTTPException(
                status_code=400,
                detail="Could not determine trigger timing (BEFORE/AFTER/INSTEAD OF). "
                       "Please provide explicit trigger metadata."
            )

    conversion_req = ConversionRequest(
        sql=req.sql,
        object_type=req.object_type,
        schema=req.schema_name,
        name=req.object_name
    )

    # OPS-01: Offload to executor to prevent event loop blocking
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, lambda: service.convert(conversion_req))

    if not result.success:
        logger.warning(
            "Conversion completed with errors",
            object_type=req.object_type,
            errors=result.errors,
        )
    return ConvertResponse(
        converted_sql=result.converted_sql,
        success=result.success,
        warnings=result.warnings,
        errors=result.errors,
        postgres_syntax_valid=result.postgres_syntax_valid,
        postgres_syntax_errors=[
            PostgresSyntaxIssueResponse(
                message=issue.message,
                line=issue.line,
                position=issue.position,
            )
            for issue in result.postgres_syntax_errors
        ],
        postgres_syntax_warnings=result.postgres_syntax_warnings,
        repairs_applied=[
            AppliedRepairResponse(
                fixer=repair.fixer,
                description=repair.description,
                line=repair.line,
            )
            for repair in result.repairs_applied
        ],
        repair_exhausted=result.repair_exhausted,
        parse_unblockers_applied=list(result.parse_unblockers_applied),
        body_transform_fallback=result.body_transform_fallback,
        manual_review_required=result.manual_review_required,
    )


@router.post("/sql/validate")
async def validate_sql(req: ConvertRequest, _: dict = require_role(UserRole.OPERATOR)):
    from domains.parsing.sqlglot_adapter import SqlglotParser
    parser = SqlglotParser()
    try:
        result = parser.parse(req.sql)
        if result.success:
            return {"valid": True, "errors": [], "dialect": result.dialect}
        return {
            "valid": False,
            "errors": [str(e) for e in (result.errors or [])],
            "dialect": result.dialect,
        }
    except Exception as exc:
        return {"valid": False, "errors": [str(exc)], "dialect": "tsql"}
