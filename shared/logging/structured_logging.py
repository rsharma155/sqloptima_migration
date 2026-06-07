"""
Module: structured_logging.py
Purpose: Structured logging configuration with file-based rotating handlers
         for persistent error analysis and debugging.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import re
import sys
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import structlog

SENSITIVE_KEYS = frozenset({
    "password", "passwd", "pwd", "secret", "token", "api_key",
    "apiKey", "api_secret", "apikey", "access_key", "accessKey",
    "private_key", "privateKey", "connection_string", "connectionString",
    "dsn", "credentials", "auth_token", "authorization",
})

SENSITIVE_PATTERNS: list[tuple[str, str]] = [
    ("password", "***"),
    ("token", "***"),
    ("secret", "***"),
    ("key", "***"),
    ("credential", "***"),
]

# Column-name heuristics aligned with pii_classifier (§12.7)
PII_COLUMN_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"ssn|social.?security|national.?id|tax.?id|passport",
        r"email|e_mail|mail_addr",
        r"phone|mobile|cell|fax|telephone",
        r"card.?number|credit.?card|pan|cvv",
        r"password|passwd|secret|token|api.?key",
        r"dob|date.?of.?birth|birth.?date",
    )
]

PII_VALUE_PLACEHOLDER = "[REDACTED_PII]"

# Default log directory — can be overridden via MIGRATION_LOG_DIR env var
_DEFAULT_LOG_DIR = Path(__file__).resolve().parents[2] / "logs"


def _redact_value(key: str, value: Any) -> Any:
    key_lower = key.lower()
    for sensitive_key in SENSITIVE_KEYS:
        if sensitive_key in key_lower:
            return "***"
    if any(p.search(key_lower) for p in PII_COLUMN_PATTERNS):
        return PII_VALUE_PLACEHOLDER
    if isinstance(value, str):
        for pattern, _replacement in SENSITIVE_PATTERNS:
            if pattern in value.lower():
                return "***"
        return value
    if isinstance(value, dict):
        return {k: _redact_value(str(k), v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(key, item) for item in value[:20]]
    return value


def redact_sensitive_data(logger: Any, method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    return {key: _redact_value(str(key), value) for key, value in event_dict.items()}


_PREDEFINED_PROCESSORS: list[Any] = [
    structlog.contextvars.merge_contextvars,
    structlog.processors.add_log_level,
    structlog.processors.TimeStamper(fmt="iso", utc=True),
    redact_sensitive_data,
    structlog.dev.ConsoleRenderer(),  # handles exc_info internally
]

# Separate processor chain for JSON output (e.g. container logs)
_JSON_PROCESSORS: list[Any] = [
    structlog.contextvars.merge_contextvars,
    structlog.processors.add_log_level,
    structlog.processors.TimeStamper(fmt="iso", utc=True),
    redact_sensitive_data,
    structlog.processors.format_exc_info,
    structlog.processors.JSONRenderer(),
]


def _build_log_dir() -> Path:
    log_dir = Path(os.environ.get("MIGRATION_LOG_DIR", str(_DEFAULT_LOG_DIR)))
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def _setup_file_handlers(log_dir: Path, level: str = "INFO") -> None:
    """Add rotating file handlers to the root stdlib logger.

    Two files are maintained:
    - ``app.log``   — all messages at *level* and above (max 10 MB × 5 backups)
    - ``error.log`` — ERROR and CRITICAL only (max 5 MB × 10 backups)

    Both files use JSON lines so they can be grepped, tailed, or ingested by
    log aggregators without extra parsing.
    """
    root = logging.getLogger()
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    formatter = logging.Formatter(
        fmt='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":%(message)s}',
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    # Full application log
    app_handler = logging.handlers.RotatingFileHandler(
        log_dir / "app.log",
        maxBytes=10 * 1024 * 1024,   # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    app_handler.setLevel(numeric_level)
    app_handler.setFormatter(formatter)

    # Error-only log (easier to scan for issues)
    error_handler = logging.handlers.RotatingFileHandler(
        log_dir / "error.log",
        maxBytes=5 * 1024 * 1024,    # 5 MB
        backupCount=10,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)

    # Avoid adding duplicate handlers on re-configuration
    existing_files = {
        h.baseFilename
        for h in root.handlers
        if isinstance(h, logging.handlers.RotatingFileHandler)
    }
    if str(log_dir / "app.log") not in existing_files:
        root.addHandler(app_handler)
    if str(log_dir / "error.log") not in existing_files:
        root.addHandler(error_handler)


def configure_logging(
    level: str = "INFO",
    json_output: bool = False,
    log_to_file: bool = True,
    log_dir: Path | None = None,
) -> None:
    """Configure structlog + stdlib logging.

    Args:
        level:       Minimum log level (e.g. "DEBUG", "INFO", "WARNING").
        json_output: Emit JSON lines to stdout (good for containerised deploys).
        log_to_file: Write rotating files under *log_dir* / ``MIGRATION_LOG_DIR``.
        log_dir:     Override the log directory (defaults to ``<repo>/logs/``).
    """
    processors = (_JSON_PROCESSORS if json_output else _PREDEFINED_PROCESSORS).copy()

    numeric_level = getattr(logging, level.upper(), logging.INFO)

    # Configure stdlib root logger so third-party libraries (uvicorn, sqlalchemy,
    # asyncpg …) are also captured in the file logs.
    logging.basicConfig(
        level=numeric_level,
        stream=sys.stdout,
        format="%(message)s",
    )

    if log_to_file:
        resolved_dir = log_dir or _build_log_dir()
        _setup_file_handlers(resolved_dir, level)

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name or __name__)


class LoggerContext:
    def __init__(
        self,
        correlation_id: UUID | None = None,
        **extra_context: Any,
    ):
        self.correlation_id = correlation_id or uuid4()
        self.extra_context = extra_context

    def __enter__(self) -> UUID:
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            correlation_id=str(self.correlation_id),
            **self.extra_context,
        )
        return self.correlation_id

    def __exit__(self, *args: Any) -> None:
        structlog.contextvars.clear_contextvars()
