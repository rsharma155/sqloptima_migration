"""
Module: domains/migration/column_transforms.py
Purpose: Fix F.4 — per-column value transforms applied at extraction time so
         type mismatches (e.g. bit→bool, datetime2→timestamptz, money→decimal)
         are resolved before rows are inserted into PostgreSQL via COPY.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

import hashlib
import re
from decimal import Decimal
from datetime import datetime, timezone
from typing import Any, Callable

# A column transform is any callable that converts a single cell value.
ColumnTransform = Callable[[Any], Any]


def bit_to_bool(value: Any) -> bool | None:
    """Convert SQL Server BIT (0/1/None) to Python bool."""
    if value is None:
        return None
    return bool(value)


def money_to_decimal(value: Any) -> Decimal | None:
    """Convert SQL Server money/smallmoney (often returned as float) to Decimal."""
    if value is None:
        return None
    return Decimal(str(value))


def datetime_to_utc(value: Any) -> datetime | None:
    """Attach UTC timezone to a naive datetime returned by pyodbc for datetime2 columns."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    return value


def strip_trailing_nulls(value: Any) -> Any:
    """Strip embedded NUL characters that can appear in nchar/ntext columns."""
    if isinstance(value, str):
        return value.rstrip("\x00")
    return value


def identity(value: Any) -> Any:
    return value


def mask_nullify(value: Any) -> None:
    """Replace any value with NULL — for regulated columns in lower environments."""
    return None


def mask_redact(value: Any) -> str | None:
    """Replace with a fixed redaction token."""
    if value is None:
        return None
    return "***REDACTED***"


def mask_hash(value: Any) -> str | None:
    """One-way SHA-256 hash (hex) preserving NULL."""
    if value is None:
        return None
    return hashlib.sha256(str(value).encode()).hexdigest()


def mask_tokenize(value: Any) -> str | None:
    """Deterministic per-value token (not reversible)."""
    if value is None:
        return None
    digest = hashlib.sha256(str(value).encode()).hexdigest()[:12]
    return f"TOK_{digest}"


def mask_partial_email(value: Any) -> str | None:
    """Keep first char + domain, mask local part — format-preserving for emails."""
    if value is None:
        return None
    text = str(value)
    if "@" not in text:
        return mask_redact(text)
    local, _, domain = text.partition("@")
    if not local:
        return f"*@{domain}"
    return f"{local[0]}***@{domain}"


def mask_last_four(value: Any) -> str | None:
    """Keep last 4 characters only (PCI-style partial masking)."""
    if value is None:
        return None
    text = re.sub(r"\D", "", str(value))
    if len(text) <= 4:
        return "****"
    return f"****{text[-4:]}"


def mask_fpe_numeric(value: Any) -> str | None:
    """Format-preserving encryption for numeric strings (same length, different digits)."""
    if value is None:
        return None
    raw = str(value)
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return mask_redact(raw)
    h = hashlib.sha256(digits.encode()).hexdigest()
    mapped = "".join(str(int(h[i], 16) % 10) for i in range(len(digits)))
    # Preserve non-digit separators from original (e.g. card spacing)
    out, di = [], 0
    for ch in raw:
        if ch.isdigit():
            out.append(mapped[di])
            di += 1
        else:
            out.append(ch)
    return "".join(out)


# Built-in named transforms
BUILT_IN_TRANSFORMS: dict[str, ColumnTransform] = {
    "bit_to_bool": bit_to_bool,
    "money_to_decimal": money_to_decimal,
    "datetime_to_utc": datetime_to_utc,
    "strip_trailing_nulls": strip_trailing_nulls,
    "identity": identity,
    # §12.2 PII masking transforms
    "mask_nullify": mask_nullify,
    "mask_redact": mask_redact,
    "mask_hash": mask_hash,
    "mask_tokenize": mask_tokenize,
    "mask_partial_email": mask_partial_email,
    "mask_last_four": mask_last_four,
    "mask_fpe_numeric": mask_fpe_numeric,
}

# Default masking policy per sensitivity class (from pii_classifier)
_SENSITIVITY_DEFAULT_MASK: dict[str, str] = {
    "pii": "mask_hash",
    "phi": "mask_nullify",
    "pci": "mask_fpe_numeric",
    "credential": "mask_nullify",
}

# SQL Server type → default transform name
_TYPE_DEFAULTS: dict[str, str] = {
    "bit": "bit_to_bool",
    "money": "money_to_decimal",
    "smallmoney": "money_to_decimal",
    "datetime2": "datetime_to_utc",
    "datetime": "datetime_to_utc",
    "smalldatetime": "datetime_to_utc",
    "nchar": "strip_trailing_nulls",
    "char": "strip_trailing_nulls",
}


class ColumnTransformPipeline:
    """Applies a chain of named transforms to each column in a row.

    Fix F.4: without explicit transforms, SQL Server BIT columns arrive as int
    (0/1) and are rejected by PostgreSQL BOOLEAN columns via COPY.  Similarly,
    naive datetimes are stored as timestamptz which defaults to the server
    timezone instead of UTC.

    Usage::

        pipeline = ColumnTransformPipeline()
        pipeline.register("is_active", "bit_to_bool")
        pipeline.register("amount", "money_to_decimal")

        clean_row = pipeline.apply({"is_active": 1, "amount": 9.99, "name": "Alice"})
        # → {"is_active": True, "amount": Decimal("9.99"), "name": "Alice"}
    """

    def __init__(self) -> None:
        self._transforms: dict[str, list[ColumnTransform]] = {}

    def register(self, column_name: str, transform_name: str) -> None:
        """Register a named transform for a column."""
        fn = BUILT_IN_TRANSFORMS.get(transform_name)
        if fn is None:
            raise ValueError(
                f"Unknown transform '{transform_name}'. "
                f"Available: {sorted(BUILT_IN_TRANSFORMS)}"
            )
        self._transforms.setdefault(column_name, []).append(fn)

    def register_fn(self, column_name: str, fn: ColumnTransform) -> None:
        """Register a custom callable for a column."""
        self._transforms.setdefault(column_name, []).append(fn)

    def apply(self, row: dict[str, Any]) -> dict[str, Any]:
        """Apply all registered transforms to a single row dict."""
        result = {}
        for col, val in row.items():
            transforms = self._transforms.get(col, [])
            for fn in transforms:
                val = fn(val)
            result[col] = val
        return result

    def apply_batch(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Apply transforms to a list of rows."""
        return [self.apply(row) for row in rows]

    @classmethod
    def from_type_map(cls, column_types: dict[str, str]) -> "ColumnTransformPipeline":
        """Build a pipeline automatically from a column→SQL-Server-type mapping.

        Columns with no default transform are left unchanged (identity).
        """
        pipeline = cls()
        for col, sql_type in column_types.items():
            transform_name = _TYPE_DEFAULTS.get(sql_type.lower())
            if transform_name:
                pipeline.register(col, transform_name)
        return pipeline

    @classmethod
    def from_transform_map(cls, transforms: dict[str, str]) -> "ColumnTransformPipeline":
        """Build a pipeline from an explicit column→transform-name mapping."""
        pipeline = cls()
        for col, transform_name in transforms.items():
            pipeline.register(col, transform_name)
        return pipeline

    @classmethod
    def from_sensitivity_map(
        cls,
        column_sensitivity: dict[str, str],
        overrides: dict[str, str] | None = None,
    ) -> "ColumnTransformPipeline":
        """Auto-apply masking transforms from PII classifier sensitivity tags."""
        pipeline = cls()
        overrides = overrides or {}
        for col, sensitivity in column_sensitivity.items():
            if sensitivity == "none":
                continue
            transform_name = overrides.get(col) or _SENSITIVITY_DEFAULT_MASK.get(sensitivity)
            if transform_name:
                pipeline.register(col, transform_name)
        return pipeline


def build_pipeline_for_plan(
    column_transforms: dict[str, str] | None = None,
    column_sensitivity: dict[str, str] | None = None,
    column_types: dict[str, str] | None = None,
) -> ColumnTransformPipeline | None:
    """Compose type-coercion + explicit + sensitivity-driven transforms for a plan."""
    if not column_transforms and not column_sensitivity and not column_types:
        return None
    pipeline = ColumnTransformPipeline()
    if column_types:
        for col, sql_type in column_types.items():
            name = _TYPE_DEFAULTS.get(sql_type.lower())
            if name:
                pipeline.register(col, name)
    if column_sensitivity:
        sens_pipeline = ColumnTransformPipeline.from_sensitivity_map(
            column_sensitivity,
            overrides=column_transforms,
        )
        for col, fns in sens_pipeline._transforms.items():
            for fn in fns:
                pipeline.register_fn(col, fn)
    elif column_transforms:
        for col, name in column_transforms.items():
            if col not in pipeline._transforms:
                pipeline.register(col, name)
    return pipeline if pipeline._transforms else None
