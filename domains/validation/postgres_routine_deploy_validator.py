"""
Module: postgres_routine_deploy_validator.py
Purpose: Validate converted PL/pgSQL by compiling it on the target PostgreSQL server.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from domains.migration.procedural_migration_models import ProceduralObjectKind
from shared.kernel.ddl_identifier import quote_pg_ident
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)

_DOLLAR_TAG_RE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)?\$", re.MULTILINE)

_ROUTINE_METADATA_SQL = """
SELECT
  p.oid,
  p.prokind,
  p.proretset,
  t.typname AS ret_type,
  pg_get_function_identity_arguments(p.oid) AS identity_args,
  p.oid::regprocedure::text AS regproc
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
JOIN pg_type t ON t.oid = p.prorettype
WHERE n.nspname = $1
  AND p.proname = $2
  AND p.prokind = $3
ORDER BY p.oid DESC
LIMIT 1
"""


@dataclass
class SmokeCallPlan:
    """Planned zero-argument runtime smoke invocation for a deployed routine."""

    eligible: bool
    sql: str = ""
    skip_reason: str = ""


@dataclass
class RoutineDeployResult:
    """Outcome of deploying and verifying a routine on PostgreSQL."""

    applied: bool
    target_validated: bool
    errors: list[str]
    statements_executed: int = 0
    runtime_smoke_executed: bool = False
    runtime_smoke_passed: bool = False
    runtime_smoke_skipped: bool = False
    runtime_smoke_message: str = ""


def split_sql_script(sql: str) -> list[str]:
    """Split a SQL script on semicolons outside quotes and dollar-quoted bodies."""
    text = sql.strip()
    if not text:
        return []

    statements: list[str] = []
    current: list[str] = []
    i = 0
    in_single = False
    dollar_tag: str | None = None

    while i < len(text):
        if dollar_tag is not None:
            match = _DOLLAR_TAG_RE.match(text, i)
            if match and match.group(0) == f"${dollar_tag}$":
                current.append(match.group(0))
                i += len(match.group(0))
                dollar_tag = None
                continue
            current.append(text[i])
            i += 1
            continue

        if not in_single:
            match = _DOLLAR_TAG_RE.match(text, i)
            if match:
                tag = match.group(1) or ""
                dollar_tag = tag
                current.append(match.group(0))
                i += len(match.group(0))
                continue

        ch = text[i]
        if ch == "'" and not in_single:
            in_single = True
            current.append(ch)
        elif ch == "'" and in_single:
            if i + 1 < len(text) and text[i + 1] == "'":
                current.append("''")
                i += 1
            else:
                in_single = False
                current.append(ch)
        elif ch == ";" and not in_single:
            stmt = "".join(current).strip()
            if stmt:
                statements.append(stmt if stmt.endswith(";") else f"{stmt};")
            current = []
        else:
            current.append(ch)
        i += 1

    tail = "".join(current).strip()
    if tail:
        statements.append(tail if tail.endswith(";") else f"{tail};")
    return statements


def _pg_object_name(name: str) -> str:
    """Return the stored PostgreSQL identifier (unquoted names fold to lower case)."""
    trimmed = name.strip()
    if trimmed.startswith('"') and trimmed.endswith('"'):
        return trimmed[1:-1]
    return trimmed.lower()


def _prokind(kind: ProceduralObjectKind) -> str:
    return "p" if kind == ProceduralObjectKind.PROCEDURE else "f"


def build_smoke_call_plan(
    target_schema: str,
    object_name: str,
    *,
    prokind: str,
    proretset: bool,
    ret_type: str,
    identity_args: str | None,
) -> SmokeCallPlan:
    """Build a zero-argument smoke call when the routine has no required inputs."""
    required = (identity_args or "").strip()
    if required:
        return SmokeCallPlan(
            eligible=False,
            skip_reason=(
                f"Runtime smoke skipped — routine requires arguments: {required}"
            ),
        )

    qschema = quote_pg_ident(target_schema)
    qname = quote_pg_ident(object_name)

    if prokind == "p":
        return SmokeCallPlan(eligible=True, sql=f"CALL {qschema}.{qname}();")

    if proretset:
        return SmokeCallPlan(
            eligible=True,
            sql=f"SELECT * FROM {qschema}.{qname}() AS _smoke LIMIT 0;",
        )

    if ret_type == "void":
        return SmokeCallPlan(eligible=True, sql=f"SELECT {qschema}.{qname}();")

    return SmokeCallPlan(eligible=True, sql=f"SELECT {qschema}.{qname}();")


async def _run_runtime_smoke(
    conn: Any,
    *,
    target_schema: str,
    pg_name: str,
    prokind: str,
    proretset: bool,
    ret_type: str,
    identity_args: str | None,
    timeout: float,
) -> tuple[bool, bool, str]:
    """Execute smoke call inside the deploy transaction. Returns (executed, passed, message)."""
    plan = build_smoke_call_plan(
        target_schema,
        pg_name,
        prokind=prokind,
        proretset=bool(proretset),
        ret_type=str(ret_type or ""),
        identity_args=identity_args,
    )
    if not plan.eligible:
        return False, False, plan.skip_reason

    await conn.execute(plan.sql, timeout=timeout)
    return True, True, f"Runtime smoke call succeeded: {plan.sql}"


async def deploy_and_verify_routine(
    connector: Any,
    *,
    sql: str,
    target_schema: str,
    object_name: str,
    object_kind: ProceduralObjectKind,
) -> RoutineDeployResult:
    """Deploy converted DDL on PostgreSQL, verify catalog entry, and run a smoke call.

    Compile verification, catalog lookup, and runtime smoke all run in one
    transaction — a failed smoke call rolls back the CREATE.
    """
    statements = split_sql_script(sql)
    if not statements:
        return RoutineDeployResult(
            applied=False,
            target_validated=False,
            errors=["Converted SQL contains no executable statements"],
        )

    pool = getattr(connector, "_pool", None)
    if pool is None:
        return RoutineDeployResult(
            applied=False,
            target_validated=False,
            errors=["PostgreSQL connector is not connected"],
        )

    pg_name = _pg_object_name(object_name)
    prokind = _prokind(object_kind)
    timeout = getattr(getattr(connector, "_config", None), "statement_timeout_seconds", 30.0)

    smoke_executed = False
    smoke_passed = False
    smoke_skipped = False
    smoke_message = ""

    try:
        regproc: str | None = None
        async with pool.acquire() as conn, conn.transaction():
            for stmt in statements:
                await conn.execute(stmt, timeout=timeout)
            row = await conn.fetchrow(
                _ROUTINE_METADATA_SQL,
                target_schema,
                pg_name,
                prokind,
                timeout=timeout,
            )
            if row is None:
                raise RuntimeError(
                    f"Routine {target_schema}.{pg_name} was not found in pg_proc after CREATE "
                    f"(kind={prokind})"
                )
            regproc = str(row["regproc"])
            try:
                smoke_executed, smoke_passed, smoke_message = await _run_runtime_smoke(
                    conn,
                    target_schema=target_schema,
                    pg_name=pg_name,
                    prokind=str(row["prokind"]),
                    proretset=bool(row["proretset"]),
                    ret_type=str(row["ret_type"] or ""),
                    identity_args=row["identity_args"],
                    timeout=timeout,
                )
            except Exception as smoke_exc:
                raise RuntimeError(
                    f"Runtime smoke call failed for {target_schema}.{pg_name}: {smoke_exc}"
                ) from smoke_exc
            if not smoke_executed:
                smoke_skipped = True

        logger.info(
            "routine_deploy_validated",
            schema=target_schema,
            name=pg_name,
            kind=prokind,
            regproc=regproc,
            runtime_smoke_executed=smoke_executed,
            runtime_smoke_skipped=smoke_skipped,
        )
        return RoutineDeployResult(
            applied=True,
            target_validated=True,
            errors=[],
            statements_executed=len(statements),
            runtime_smoke_executed=smoke_executed,
            runtime_smoke_passed=smoke_passed,
            runtime_smoke_skipped=smoke_skipped,
            runtime_smoke_message=smoke_message,
        )
    except Exception as exc:
        logger.warning(
            "routine_deploy_failed",
            schema=target_schema,
            name=pg_name,
            kind=prokind,
            error=str(exc),
        )
        return RoutineDeployResult(
            applied=False,
            target_validated=False,
            errors=[f"Target PostgreSQL rejected routine: {exc}"],
            statements_executed=0,
            runtime_smoke_executed=smoke_executed,
            runtime_smoke_passed=False,
            runtime_smoke_skipped=smoke_skipped,
            runtime_smoke_message=smoke_message,
        )
