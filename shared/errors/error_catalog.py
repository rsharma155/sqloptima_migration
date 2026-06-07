"""Stable error-code catalog with plain-language remediation (§13.11).
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class PlatformError:
    code: str
    title: str
    cause: str
    remediation: str
    doc_anchor: str = ""


_CATALOG: dict[str, PlatformError] = {
    "CONN_SOURCE_UNREACHABLE": PlatformError(
        code="CONN_SOURCE_UNREACHABLE",
        title="Cannot reach SQL Server",
        cause="The source host refused the connection or timed out.",
        remediation="Verify host/port, firewall rules, and that SQL Server accepts TCP connections.",
        doc_anchor="operations#connection-errors",
    ),
    "CONN_TARGET_UNREACHABLE": PlatformError(
        code="CONN_TARGET_UNREACHABLE",
        title="Cannot reach PostgreSQL",
        cause="The target host refused the connection or timed out.",
        remediation="Verify host/port, pg_hba.conf, and that PostgreSQL is listening.",
        doc_anchor="operations#connection-errors",
    ),
    "CONN_AUTH_FAILED": PlatformError(
        code="CONN_AUTH_FAILED",
        title="Database authentication failed",
        cause="Username or password was rejected by the database.",
        remediation="Re-enter credentials in Connections; confirm the account exists and is unlocked.",
        doc_anchor="operations#connection-errors",
    ),
    "MIG_SNAPSHOT_REQUIRED": PlatformError(
        code="MIG_SNAPSHOT_REQUIRED",
        title="Target snapshot required",
        cause="Migration start blocked because no verified target backup exists.",
        remediation="Run pg_dump on the target, pass snapshot_ref, or set require_target_snapshot=false for dev.",
        doc_anchor="operations#snapshot-gate",
    ),
    "MIG_MASKING_STRICT": PlatformError(
        code="MIG_MASKING_STRICT",
        title="Sensitive data masking required",
        cause="Strict masking policy found PII/PCI columns without approved transforms.",
        remediation="Use masking_policy=auto or provide column_transforms for sensitive columns.",
        doc_anchor="operations#pii-masking",
    ),
    "VAL_SCHEMA_MISMATCH": PlatformError(
        code="VAL_SCHEMA_MISMATCH",
        title="Schema validation failed",
        cause="Source and target column types or constraints do not match.",
        remediation="Review validation report mismatches before cutover.",
        doc_anchor="operations#validation",
    ),
    "INTERNAL_ERROR": PlatformError(
        code="INTERNAL_ERROR",
        title="Unexpected platform error",
        cause="An unhandled exception occurred in the migration platform.",
        remediation="Check API logs (error.log) and retry; contact support with the correlation ID.",
        doc_anchor="operations#support",
    ),
}

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)login failed|authentication failed|password"), "CONN_AUTH_FAILED"),
    (re.compile(r"(?i)hyt00|login timeout|timeout expired|timed out"), "CONN_SOURCE_UNREACHABLE"),
    (re.compile(r"(?i)pyodbc|sql server|1433|connection.*refused|odbc driver"), "CONN_SOURCE_UNREACHABLE"),
    (re.compile(r"(?i)asyncpg|postgres|5432|pg_hba|host is down|errno 64|no route to host"), "CONN_TARGET_UNREACHABLE"),
    (re.compile(r"(?i)snapshot gate|pg_dump|require.*snapshot"), "MIG_SNAPSHOT_REQUIRED"),
    (re.compile(r"(?i)strict masking|sensitive column"), "MIG_MASKING_STRICT"),
    (re.compile(r"(?i)schema.*mismatch|validation failed"), "VAL_SCHEMA_MISMATCH"),
]


def classify_error(message: str) -> PlatformError:
    """Map a raw exception/message string to a catalog entry."""
    for pattern, code in _PATTERNS:
        if pattern.search(message):
            return _CATALOG[code]
    return _CATALOG["INTERNAL_ERROR"]


def format_error_response(message: str, *, correlation_id: str | None = None) -> dict:
    """Build API-safe error payload (no raw stack traces)."""
    err = classify_error(message)
    payload: dict = {
        "error_code": err.code,
        "title": err.title,
        "cause": err.cause,
        "remediation": err.remediation,
        "doc_anchor": err.doc_anchor,
    }
    if correlation_id:
        payload["correlation_id"] = correlation_id
    return payload


def format_connection_error(
    message: str,
    *,
    conn_type: str = "source",
    correlation_id: str | None = None,
) -> dict:
    """Build a 502 payload for database connectivity failures."""
    payload = format_error_response(message, correlation_id=correlation_id)
    if conn_type == "target" and payload["error_code"] == "CONN_SOURCE_UNREACHABLE":
        err = _CATALOG["CONN_TARGET_UNREACHABLE"]
        payload.update(
            error_code=err.code,
            title=err.title,
            cause=err.cause,
            remediation=err.remediation,
            doc_anchor=err.doc_anchor,
        )
    elif conn_type == "source" and payload["error_code"] == "CONN_TARGET_UNREACHABLE":
        err = _CATALOG["CONN_SOURCE_UNREACHABLE"]
        payload.update(
            error_code=err.code,
            title=err.title,
            cause=err.cause,
            remediation=err.remediation,
            doc_anchor=err.doc_anchor,
        )
    return payload


def _extract_driver_message(message: str) -> str:
    """Pull readable text out of pyodbc/asyncpg exception strings."""
    if not message:
        return message

    odbc = re.search(
        r"\[Microsoft\]\[ODBC Driver[^\]]*\](.+?)(?:\s*\(\d+\))?\s*(?:\(SQLDriverConnect\))?",
        message,
        re.IGNORECASE,
    )
    if odbc:
        return odbc.group(1).strip()

    bracket = re.search(r"\[HYT\d+\]\s*(.+?)(?:\s*\(\d+\))?", message, re.IGNORECASE)
    if bracket:
        return bracket.group(1).strip()

    errno = re.search(r"\[Errno \d+\]\s*(.+)", message, re.IGNORECASE)
    if errno:
        return errno.group(1).strip()

    return message.strip()


def _resolve_connection_error(message: str, *, conn_type: str) -> PlatformError:
    """Classify a driver error, using connection type as a hint."""
    err = classify_error(message)
    if conn_type == "target" and err.code in ("CONN_SOURCE_UNREACHABLE", "INTERNAL_ERROR"):
        if re.search(r"(?i)host is down|errno|refused|timeout|asyncpg|postgres|5432", message):
            return _CATALOG["CONN_TARGET_UNREACHABLE"]
    if conn_type == "source" and err.code in ("CONN_TARGET_UNREACHABLE", "INTERNAL_ERROR"):
        if re.search(r"(?i)hyt00|pyodbc|odbc|sql server|1433|timeout", message):
            return _CATALOG["CONN_SOURCE_UNREACHABLE"]
    return err


def humanize_connection_message(
    message: str,
    *,
    conn_type: str = "source",
    host: str | None = None,
    port: int | None = None,
) -> str:
    """Turn raw driver exceptions into plain-language connection test messages."""
    raw = message or "Unknown connection error"
    cleaned = _extract_driver_message(raw)
    err = _resolve_connection_error(f"{raw} {cleaned}", conn_type=conn_type)

    label = "SQL Server" if conn_type == "source" else "PostgreSQL"
    default_port = 1433 if conn_type == "source" else 5432
    endpoint = f" ({host}:{port or default_port})" if host else ""

    if err.code == "CONN_AUTH_FAILED":
        return (
            f"{label}{endpoint}: login was rejected. "
            "Check the username and password in Settings."
        )

    if re.search(r"(?i)hyt00|login timeout|timeout expired", raw):
        return (
            f"{label}{endpoint}: connection timed out. "
            f"The server may be offline, the host or port may be wrong, or a firewall "
            f"may be blocking port {port or default_port}. "
            "If using Docker, run: docker-compose up -d"
        )

    if re.search(r"(?i)host is down|errno 64|no route to host", raw):
        return (
            f"{label}{endpoint}: host is unreachable. "
            "The database server appears to be offline or the hostname is incorrect. "
            "Start the database service and verify the host in Settings."
        )

    if re.search(r"(?i)connection refused|actively refused", raw):
        return (
            f"{label}{endpoint}: connection refused. "
            f"Nothing is listening on port {port or default_port}. "
            "Start the database service or check the port number."
        )

    if re.search(r"(?i)name or service not known|nodename nor servname", raw):
        return (
            f"{label}{endpoint}: hostname could not be resolved. "
            "Check the server address in Settings."
        )

    if err.code in ("CONN_SOURCE_UNREACHABLE", "CONN_TARGET_UNREACHABLE"):
        return f"{label}{endpoint}: {err.cause} {err.remediation}"

    summary = cleaned if cleaned and cleaned != raw else raw
    return f"{label}{endpoint}: {summary}"
