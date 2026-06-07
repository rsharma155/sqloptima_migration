"""
Module: parser_port.py
Purpose: Abstract port interface for SQL parsers
Author: Migration Platform Team
Created: 2026-05-22
Domain: Parsing
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from abc import ABC, abstractmethod
from typing import Any


class ParseResult:
    """Result of parsing a SQL statement."""

    def __init__(
        self,
        success: bool,
        ast: Any | None = None,
        errors: list[str] = None,
        dialect: str = "",
    ):
        self.success = success
        self.ast = ast
        self.errors = errors or []
        self.dialect = dialect


class SqlParser(ABC):
    """Abstract port for SQL parsing."""

    @abstractmethod
    def parse(self, sql: str) -> ParseResult:
        """Parse a SQL string into an AST."""

    @abstractmethod
    def parse_multiple(self, sql: str) -> list[ParseResult]:
        """Parse multiple SQL statements."""

    @property
    @abstractmethod
    def dialect(self) -> str:
        """Return the source dialect this parser handles."""
