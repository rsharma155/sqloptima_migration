"""
Package: domains/transpilation/converters/plpgsql
Purpose: T-SQL → PL/pgSQL conversion sub-package.

Public API
----------
The primary entry point is :class:`TsqlToPlpgsqlConverter`.  All other names
are re-exported here for convenience but are considered semi-internal.

Example::

    from domains.transpilation.converters.plpgsql import TsqlToPlpgsqlConverter
    pg_sql = TsqlToPlpgsqlConverter().convert(tsql_text)

Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from domains.transpilation.converters.plpgsql._models import (
    HeaderInfo,
    ParamInfo,
    SprocType,
)
from domains.transpilation.converters.plpgsql._type_mapper import TsqlTypeMapper
from domains.transpilation.converters.plpgsql._header_parser import (
    TsqlHeaderParser,
    _extract_body,
    _split_params,
)
from domains.transpilation.converters.plpgsql._body_transforms import TsqlBodyConverter
from domains.transpilation.converters.plpgsql._output_builder import TsqlToPlpgsqlConverter

__all__ = [
    # Primary entry point
    "TsqlToPlpgsqlConverter",
    # Supporting classes (used by ProceduralConverter for metadata extraction)
    "TsqlHeaderParser",
    "TsqlBodyConverter",
    "TsqlTypeMapper",
    # Data models
    "SprocType",
    "ParamInfo",
    "HeaderInfo",
]
