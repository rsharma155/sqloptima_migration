"""
Module: domains/transpilation/converters/plpgsql/_xml_converter.py
Purpose: T-SQL FOR XML PATH / OPENXML conversion helper.
         Re-exports _convert_for_xml_path from _body_transforms so tests
         can import it directly from this module.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from domains.transpilation.converters.plpgsql._body_transforms import (  # noqa: F401
    _convert_for_xml_path,
)
