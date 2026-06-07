"""
Module: domains/transpilation/converters/plpgsql/_format_converter.py
Purpose: T-SQL FORMAT() → PostgreSQL TO_CHAR() conversion helper.
         Re-exports _convert_format_function from _body_transforms so tests
         can import it directly from this module.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from domains.transpilation.converters.plpgsql._body_transforms import (  # noqa: F401
    _convert_format_function,
    _FORMAT_MAP,
)
