"""
Resilient T-SQL → PostgreSQL transpiler with parse unblockers and parser fallback.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from domains.parsing.antlr_adapter import CompositeParser
from domains.parsing.parser_port import SqlParser
from domains.parsing.tsql_parse_unblocker import TsqlParseUnblocker


@dataclass
class TranspileResult:
    """Result of resilient transpilation."""

    sql: str
    success: bool
    warnings: list[str] = field(default_factory=list)
    unblockers_applied: list[str] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)
    parser_used: str = "sqlglot"


class ResilientTranspiler:
    """Try transpile with progressive parse unblockers and CompositeParser fallback."""

    def __init__(self, parser: SqlParser | None = None) -> None:
        self._parser = parser or CompositeParser()

    @property
    def dialect(self) -> str:
        return self._parser.dialect

    def transpile(self, sql: str) -> str:
        return self.transpile_with_metadata(sql).sql

    def parse(self, sql: str):
        return self._parser.parse(sql)

    def parse_multiple(self, sql: str):
        return self._parser.parse_multiple(sql)

    def transpile_with_metadata(self, sql: str) -> TranspileResult:
        warnings: list[str] = []
        applied: list[str] = []

        # Attempt 1: raw input
        out = self._try_transpile(sql)
        if out:
            return TranspileResult(out, True, warnings, applied, [], "sqlglot")

        # Attempt 2: light unblockers
        light = TsqlParseUnblocker.apply(sql, aggressive=False)
        warnings.extend(light.warnings)
        applied.extend(light.steps_applied)
        out = self._try_transpile(light.sql)
        if out:
            return TranspileResult(out, True, warnings, applied, [], "sqlglot")

        # Attempt 3: aggressive unblockers
        aggressive = TsqlParseUnblocker.apply(light.sql, aggressive=True)
        warnings.extend(aggressive.warnings)
        applied.extend(aggressive.steps_applied)
        out = self._try_transpile(aggressive.sql)
        if out:
            return TranspileResult(out, True, warnings, applied, [], "sqlglot")

        # Attempt 4: verify parse via CompositeParser; surface structured errors
        parse_result = self._parser.parse(aggressive.sql)
        parser_used = "composite"
        if parse_result.success:
            # Parsed but SQLGlot transpile failed — return preprocessed T-SQL for body-transform fallback
            warnings.append(
                "T-SQL parsed successfully but SQLGlot transpile failed; "
                "downstream body-transform fallback will be used"
            )
            return TranspileResult(
                "",
                False,
                warnings,
                applied,
                [],
                parser_used,
            )

        errors = list(parse_result.errors)
        if errors:
            warnings.append(f"T-SQL parse failed: {errors[0]}")

        return TranspileResult(
            "",
            False,
            warnings,
            applied,
            errors,
            parser_used,
        )

    @staticmethod
    def _try_transpile(sql: str) -> str | None:
        if not sql or not sql.strip():
            return None
        try:
            from domains.parsing.sqlglot_adapter import SqlglotParser

            out = SqlglotParser().transpile(sql)
            return out if out and out.strip() else None
        except Exception:
            return None
