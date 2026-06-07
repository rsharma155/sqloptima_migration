"""
Module: domains/replication/__init__.py
Purpose: Replication domain — schema drift, stream concerns, validation
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from domains.replication.cdc_requirements import CdcStatus, validate_cdc_for_tables
from domains.replication.entities import StreamConcern, StreamTableConfig
from domains.replication.schema_drift_detector import TableSchemaSnapshot, detect_schema_drift
from domains.replication.validators import validate_identifier, validate_table_list

__all__ = [
    "CdcStatus",
    "StreamConcern",
    "StreamTableConfig",
    "TableSchemaSnapshot",
    "detect_schema_drift",
    "validate_cdc_for_tables",
    "validate_identifier",
    "validate_table_list",
]
