"""
Module: domains/transpilation/converters/plpgsql/_models.py
Purpose: Core data-model types shared across the T-SQL → PL/pgSQL conversion
         sub-package.  Keeping models separate avoids circular imports between
         the parser, body-transform, and output-builder layers.

Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Optional


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class SprocType(StrEnum):
    """Whether the converted PG object should be a PROCEDURE or a FUNCTION."""

    FUNCTION  = "function"
    PROCEDURE = "procedure"


# ---------------------------------------------------------------------------
# Parameter descriptor
# ---------------------------------------------------------------------------


@dataclass
class ParamInfo:
    """A single T-SQL parameter with its converted PostgreSQL representation."""

    name: str
    pg_type: str
    is_output: bool = False
    is_readonly: bool = False
    default_value: Optional[str] = None

    @property
    def pg_declaration(self) -> str:
        """Generate the PL/pgSQL parameter declaration string.

        PostgreSQL parameter modes:
        - Input-only parameters use no prefix (``IN`` is the default).
        - Output parameters use ``INOUT`` so callers can read the updated value.
          They always get ``DEFAULT NULL`` when no explicit default was given, so
          callers may omit them.
        """
        if self.is_output:
            decl = f"INOUT p_{self.name} {self.pg_type}"
            default = self.default_value if self.default_value is not None else "NULL"
            decl += f" DEFAULT {default}"
        else:
            decl = f"p_{self.name} {self.pg_type}"
            if self.default_value is not None:
                decl += f" DEFAULT {self.default_value}"
        return decl


# ---------------------------------------------------------------------------
# Header descriptor
# ---------------------------------------------------------------------------


@dataclass
class HeaderInfo:
    """Parsed information extracted from a T-SQL CREATE PROCEDURE/FUNCTION header."""

    schema: str = "dbo"
    name: str = "usp_converted"
    parameters: list[ParamInfo] = field(default_factory=list)
    body: str = ""
    is_function: bool = False  # True when source was CREATE FUNCTION (not PROCEDURE/PROC)
