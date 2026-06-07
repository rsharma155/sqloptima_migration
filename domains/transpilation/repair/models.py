"""Data models for the conversion repair pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AppliedRepair:
    """A single repair fix applied to converted SQL."""

    fixer: str
    description: str
    line: int | None = None


@dataclass
class RepairResult:
    """Outcome of running the repair pipeline on converted SQL."""

    sql: str
    repairs: list[AppliedRepair] = field(default_factory=list)
    fixes_applied: int = 0
    repair_exhausted: bool = False
