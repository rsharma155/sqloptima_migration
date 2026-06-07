"""
Validate → fix → re-validate loop for converted PostgreSQL / PL/pgSQL output.
"""

from __future__ import annotations

import re

from domains.transpilation.repair.models import AppliedRepair, RepairResult
from domains.transpilation.repair.pg_syntax_fixers import (
    BODY_ONLY_FIXERS,
    FIXER_BY_NAME,
    PROACTIVE_FIXERS,
    fixers_for_issue_message,
)
from domains.validation.postgres_syntax_validator import PostgresSyntaxValidator

_DOLLAR_BODY_RE = re.compile(
    r"\bAS\s+\$([\w]*)\$(.*?)\$\1\s*;",
    re.IGNORECASE | re.DOTALL,
)


class ConversionRepairService:
    """Apply rule-based fixers until pgparse validation passes or rounds exhaust."""

    MAX_ROUNDS = 3

    def __init__(self, validator: PostgresSyntaxValidator | None = None) -> None:
        self._validator = validator or PostgresSyntaxValidator()

    def repair(self, sql: str) -> RepairResult:
        if not sql or not sql.strip():
            return RepairResult(sql=sql, repair_exhausted=False)

        repairs: list[AppliedRepair] = []
        current = sql

        for round_idx in range(self.MAX_ROUNDS):
            current, round_repairs = self._apply_named_fixers(current, None)
            repairs.extend(round_repairs)

            if self._is_valid(current):
                return RepairResult(
                    sql=current,
                    repairs=repairs,
                    fixes_applied=len(repairs),
                    repair_exhausted=False,
                )

            if round_idx == self.MAX_ROUNDS - 1:
                break

            targeted: list[str] = []
            for issue in self._validator.validate(current).errors:
                targeted.extend(fixers_for_issue_message(issue.message))
            if not targeted:
                break

            current, round_repairs = self._apply_named_fixers(
                current,
                self._dedupe_names(targeted),
            )
            repairs.extend(round_repairs)

            if self._is_valid(current):
                return RepairResult(
                    sql=current,
                    repairs=repairs,
                    fixes_applied=len(repairs),
                    repair_exhausted=False,
                )

        return RepairResult(
            sql=current,
            repairs=repairs,
            fixes_applied=len(repairs),
            repair_exhausted=True,
        )

    def _is_valid(self, sql: str) -> bool:
        return self._validator.validate(sql).valid

    def _error_count(self, sql: str) -> int:
        return len(self._validator.validate(sql).errors)

    def _apply_named_fixers(
        self,
        sql: str,
        fixer_names: list[str] | None,
    ) -> tuple[str, list[AppliedRepair]]:
        names = fixer_names or [name for name, _ in PROACTIVE_FIXERS + BODY_ONLY_FIXERS]
        repairs: list[AppliedRepair] = []
        current = sql

        for name in names:
            fn = FIXER_BY_NAME.get(name)
            if fn is None:
                continue
            candidate, count = fn(current)
            if count and self._accept_fix(current, candidate):
                repairs.append(
                    AppliedRepair(
                        fixer=name,
                        description=f"Applied {name} ({count} change(s))",
                    )
                )
                current = candidate

        current, body_repairs = self._repair_dollar_bodies(current, names)
        repairs.extend(body_repairs)
        return current, repairs

    def _accept_fix(self, before: str, after: str) -> bool:
        if before == after:
            return False
        return self._is_valid(after) or self._error_count(after) < self._error_count(before)

    def _repair_dollar_bodies(
        self,
        sql: str,
        fixer_names: list[str],
    ) -> tuple[str, list[AppliedRepair]]:
        match = _DOLLAR_BODY_RE.search(sql)
        if not match:
            return sql, []

        tag = match.group(1)
        body = match.group(2)
        repairs: list[AppliedRepair] = []
        current_body = body
        current_sql = sql

        for name in fixer_names:
            fn = FIXER_BY_NAME.get(name)
            if fn is None:
                continue
            candidate_body, count = fn(current_body)
            if not count:
                continue
            candidate_sql = (
                current_sql[: match.start(2)]
                + candidate_body
                + current_sql[match.end(2) :]
            )
            if self._accept_fix(current_sql, candidate_sql):
                repairs.append(
                    AppliedRepair(
                        fixer=f"{name}:body",
                        description=f"Applied {name} inside PL/pgSQL body ({count} change(s))",
                    )
                )
                current_body = candidate_body
                current_sql = candidate_sql

        return current_sql, repairs

    @staticmethod
    def _dedupe_names(names: list[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for name in names:
            if name not in seen:
                seen.add(name)
                ordered.append(name)
        return ordered
