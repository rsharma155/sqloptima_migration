"""
Module: domains/transpilation/converters/tsql_to_plpgsql.py
Purpose: Backward-compatible shim.  All implementation has been moved to the
         ``plpgsql/`` sub-package for maintainability.  This file re-exports
         every public name so existing callers do not need to change their
         imports.

         Primary entry point::

             from domains.transpilation.converters.tsql_to_plpgsql import TsqlToPlpgsqlConverter
             pg_sql = TsqlToPlpgsqlConverter().convert(tsql_text)

Domain: Transpilation
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

# Re-export everything from the sub-package so existing imports keep working.
from domains.transpilation.converters.plpgsql import (  # noqa: F401
    TsqlToPlpgsqlConverter,
    TsqlHeaderParser,
    TsqlBodyConverter,
    TsqlTypeMapper,
    SprocType,
    ParamInfo,
    HeaderInfo,
)

# Also expose the private helpers that ProceduralConverter imports by name.
from domains.transpilation.converters.plpgsql._header_parser import (  # noqa: F401
    _extract_body,
    _split_params,
)
from domains.transpilation.converters.plpgsql._body_transforms import (  # noqa: F401
    _find_if_body_start,
    _remove_session_settings,
    _convert_control_flow,
    _convert_string_concat,
    _convert_dynamic_sql,
    _convert_cursor_syntax,
    _convert_rowcount,
    _convert_raiserror,
    _convert_try_catch,
    _convert_tsql_builtin_functions,
    _convert_year_month_day,
    _convert_iif,
    _convert_top_with_ties,
    _fix_remaining_top,
    _convert_variable_references,
    _convert_set_var_assign,
    _convert_temp_tables,
    _expand_multi_var_declare,
)
