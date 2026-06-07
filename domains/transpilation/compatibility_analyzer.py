"""
Module: compatibility_analyzer.py
Purpose: Analyzes SQL Server objects for PostgreSQL compatibility
Author: Migration Platform Team
Created: 2026-05-22
Domain: Transpilation
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from shared.kernel.database_object import (
    CompatibilityStatus,
    DatabaseObject,
    DatabaseObjectType,
)


class CompatibilityIssue:
    """A single compatibility issue found during analysis."""

    def __init__(self, object_id: str, issue_type: str, severity: str, message: str):
        self.object_id = object_id
        self.issue_type = issue_type
        self.severity = severity
        self.message = message


class CompatibilityResult:
    """Result of compatibility analysis for a database object."""

    def __init__(self, obj: DatabaseObject):
        self.object = obj
        self.status: CompatibilityStatus = CompatibilityStatus.AUTO_CONVERTIBLE
        self.issues: list[CompatibilityIssue] = []
        self.auto_convertible_percentage: float = 100.0

    def add_issue(self, issue: CompatibilityIssue) -> None:
        self.issues.append(issue)
        self._recalculate_status()

    def _recalculate_status(self) -> None:
        severities = {i.severity for i in self.issues}
        if "unsupported" in severities:
            self.status = CompatibilityStatus.UNSUPPORTED
        elif "high" in severities or "medium" in severities:
            self.status = CompatibilityStatus.PARTIAL
        elif "risk" in severities:
            self.status = CompatibilityStatus.RISKY
        elif "performance" in severities:
            self.status = CompatibilityStatus.PERFORMANCE_RISK
        else:
            self.status = CompatibilityStatus.AUTO_CONVERTIBLE

        if self.issues:
            auto = max(0.0, 100.0 - len(self.issues) * 10.0)
            self.auto_convertible_percentage = auto


class CompatibilityAnalyzer:
    """Analyzes SQL Server objects for PostgreSQL compatibility.

    Classifies each object as:
    - Auto Convertible
    - Partial (requires manual fix)
    - Unsupported
    - Risky (behavior difference)
    - Performance Risk
    """

    UNSUPPORTED_FEATURES: dict[str, str] = {
        "CLR": "CLR stored procedures/functions are not supported in PostgreSQL",
        "SERVICE_BROKER": "Service Broker has no PostgreSQL equivalent",
        "LINKED_SERVER": "Linked servers require Foreign Data Wrappers (FDW) extension",
        "SQL_AGENT": "SQL Agent jobs require pgAgent or external scheduler",
    }

    RISKY_TYPES: set[str] = {
        "SQL_VARIANT", "HIERARCHYID", "GEOGRAPHY", "GEOMETRY",
        "ROWVERSION", "TIMESTAMP",
    }

    DIFFICULT_PATTERNS: dict[str, tuple[str, str]] = {
        "EXEC": ("dynamic_sql", "Dynamic SQL detected - requires manual review"),
        "sp_executesql": ("dynamic_sql", "sp_executesql detected - requires manual review"),
        "MERGE": ("merge", "MERGE statement - PostgreSQL supports via INSERT...ON CONFLICT"),
        "CROSS APPLY": ("apply", "CROSS APPLY - requires rewrite to LATERAL JOIN"),
        "OUTER APPLY": ("apply", "OUTER APPLY - requires rewrite to LATERAL JOIN"),
        "OUTPUT": ("output", "OUTPUT clause - requires trigger or RETURNING rewrite"),
        "PIVOT": ("pivot", "PIVOT - requires crosstab extension or manual rewrite"),
        "UNPIVOT": ("unpivot", "UNPIVOT - requires manual rewrite"),
        "TRY": ("try_catch", "TRY/CATCH pattern - requires PL/pgSQL exception block"),
        "RAISERROR": ("raise", "RAISERROR - requires RAISE in PL/pgSQL"),
        "PRINT": ("print", "PRINT - requires RAISE NOTICE in PL/pgSQL"),
        "WAITFOR": ("waitfor", "WAITFOR - requires pg_sleep()"),
        "IDENTITY": ("identity", "IDENTITY - maps to GENERATED AS IDENTITY"),
        "@@ROWCOUNT": ("rowcount", "@@ROWCOUNT - requires GET DIAGNOSTICS"),
        "NEWID": ("newid", "NEWID() - requires gen_random_uuid()"),
        "GETDATE": ("getdate", "GETDATE() - requires NOW()"),
        "ISNULL": ("isnull", "ISNULL() - maps to COALESCE()"),
        "TOP": ("top", "TOP N - maps to LIMIT N"),
        "LEN": ("len", "LEN() - maps to LENGTH()"),
    }

    def analyze_object(self, obj: DatabaseObject) -> CompatibilityResult:
        """Analyze a single database object for compatibility."""
        result = CompatibilityResult(obj)
        source = (obj.source_definition or "").upper()

        # Check object type
        if obj.object_type == DatabaseObjectType.PROCEDURE:
            result.add_issue(CompatibilityIssue(
                object_id=obj.fully_qualified_name,
                issue_type="procedure",
                severity="low",
                message="Stored procedure requires T-SQL to PL/pgSQL conversion",
            ))

        if obj.object_type == DatabaseObjectType.TRIGGER:
            result.add_issue(CompatibilityIssue(
                object_id=obj.fully_qualified_name,
                issue_type="trigger",
                severity="medium",
                message="Trigger requires conversion from T-SQL to PL/pgSQL",
            ))

        # Check for unsupported features
        for feature, msg in self.UNSUPPORTED_FEATURES.items():
            if feature in source:
                result.add_issue(CompatibilityIssue(
                    object_id=obj.fully_qualified_name,
                    issue_type="unsupported_feature",
                    severity="unsupported",
                    message=msg,
                ))

        # Check for difficult patterns
        for pattern, (itype, msg) in self.DIFFICULT_PATTERNS.items():
            if pattern in source:
                result.add_issue(CompatibilityIssue(
                    object_id=obj.fully_qualified_name,
                    issue_type=itype,
                    severity="medium",
                    message=msg,
                ))

        # Check for risky data types
        if hasattr(obj, "columns"):
            for col in (obj.columns or []):
                if col.data_type.type_name.upper() in self.RISKY_TYPES:
                    result.add_issue(CompatibilityIssue(
                        object_id=f"{obj.fully_qualified_name}.{col.column_name}",
                        issue_type="risky_type",
                        severity="risk",
                        message=f"Risky data type: {col.data_type.type_name}",
                    ))

        return result

    def analyze_batch(self, objects: list[DatabaseObject]) -> list[CompatibilityResult]:
        """Analyze multiple objects."""
        return [self.analyze_object(obj) for obj in objects]

    def generate_report_summary(self, results: list[CompatibilityResult]) -> dict:
        """Generate a summary report from compatibility results."""
        total = len(results)
        counts = dict.fromkeys(CompatibilityStatus, 0)
        all_issues: list[str] = []

        for r in results:
            counts[r.status] += 1
            for issue in r.issues:
                all_issues.append(f"[{r.object.fully_qualified_name}] {issue.message}")

        auto_pct = (counts[CompatibilityStatus.AUTO_CONVERTIBLE] / total * 100) if total else 0

        return {
            "total_objects": total,
            "auto_convertible": counts[CompatibilityStatus.AUTO_CONVERTIBLE],
            "partial": counts[CompatibilityStatus.PARTIAL],
            "unsupported": counts[CompatibilityStatus.UNSUPPORTED],
            "risky": counts[CompatibilityStatus.RISKY],
            "performance_risk": counts[CompatibilityStatus.PERFORMANCE_RISK],
            "auto_convertible_percentage": round(auto_pct, 1),
            "total_issues": len(all_issues),
            "issues": all_issues[:50],
        }
