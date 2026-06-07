"""Inline SELECT query runtime equivalence harness (§11.2 live path).

Converts T-SQL SELECT expressions and compares resultsets on source vs target.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

from domains.transpilation.converters.plpgsql._body_transforms import TsqlBodyConverter
from domains.validation.procedure_equivalence_harness import compare_resultsets
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)


@dataclass
class QueryEquivalenceCase:
    name: str
    source_sql: str
    tolerance: float = 0.0
    notes: str = ""


@dataclass
class QueryEquivalenceResult:
    case_name: str
    passed: bool
    source_sql: str = ""
    target_sql: str = ""
    errors: list[str] = field(default_factory=list)


def convert_tsql_query(tsql: str) -> str:
    """Convert a T-SQL SELECT to PostgreSQL using body-transform passes."""
    body = tsql.strip().rstrip(";")
    converted = TsqlBodyConverter.convert(body, [])
    converted = converted.replace("[", '"').replace("]", '"')
    converted = re.sub(r"\bdbo\.", "", converted, flags=re.IGNORECASE)
    return converted


async def build_connectors_from_env() -> tuple[Any, Any]:
    """Build source/target connectors from MIGRATION_SOURCE_* / MIGRATION_TARGET_* env."""
    from infrastructure.postgres.postgres_connector import (
        PostgresConnectionConfig,
        PostgresConnector,
    )
    from infrastructure.sqlserver.sqlserver_connector import (
        SqlServerConnectionConfig,
        SqlServerConnector,
    )

    def _req(prefix: str, key: str, default: str = "") -> str:
        val = os.environ.get(f"{prefix}_{key}", default)
        if not val:
            raise RuntimeError(f"Missing env var {prefix}_{key}")
        return val

    src = SqlServerConnector(
        SqlServerConnectionConfig(
            host=_req("MIGRATION_SOURCE", "HOST"),
            port=int(_req("MIGRATION_SOURCE", "PORT", "1433")),
            database=_req("MIGRATION_SOURCE", "DATABASE"),
            username=_req("MIGRATION_SOURCE", "USER"),
            password=_req("MIGRATION_SOURCE", "PASSWORD"),
            trust_server_certificate=os.environ.get("MIGRATION_SOURCE_TRUST_CERT", "false").lower() == "true",
        )
    )
    tgt = PostgresConnector(
        PostgresConnectionConfig(
            host=_req("MIGRATION_TARGET", "HOST"),
            port=int(_req("MIGRATION_TARGET", "PORT", "5432")),
            database=_req("MIGRATION_TARGET", "DATABASE"),
            username=_req("MIGRATION_TARGET", "USER"),
            password=_req("MIGRATION_TARGET", "PASSWORD"),
            ssl_mode=os.environ.get("MIGRATION_TARGET_SSL_MODE", "prefer"),
        )
    )
    await src.connect()
    await tgt.connect()
    return src, tgt


class QueryEquivalenceHarness:
    """Run inline SELECT equivalence cases against live connectors."""

    def __init__(self, source_connector: Any, target_connector: Any) -> None:
        self._source = source_connector
        self._target = target_connector

    async def run_case(self, case: QueryEquivalenceCase) -> QueryEquivalenceResult:
        result = QueryEquivalenceResult(
            case_name=case.name,
            passed=False,
            source_sql=case.source_sql,
        )
        try:
            target_sql = convert_tsql_query(case.source_sql)
            result.target_sql = target_sql
            source_rows = await self._source.execute(case.source_sql)
            target_rows = await self._target.execute(target_sql)
            ok, detail = compare_resultsets(source_rows, target_rows)
            if not ok:
                result.errors.append(detail)
                return result
            result.passed = True
        except Exception as exc:
            result.errors.append(f"{type(exc).__name__}: {exc}")
        return result

    async def run_corpus(self, cases: list[QueryEquivalenceCase]) -> list[QueryEquivalenceResult]:
        return [await self.run_case(c) for c in cases]
