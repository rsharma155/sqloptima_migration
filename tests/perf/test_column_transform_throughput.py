"""Performance regression gate for column transform pipeline (§11.7)."""
from __future__ import annotations

import time

import pytest

from domains.migration.column_transforms import ColumnTransformPipeline

# Baseline: 50k rows with 3 transforms in < 2s on CI runners (conservative).
_ROW_COUNT = 50_000
_MAX_SECONDS = 2.0


def test_masking_pipeline_throughput_gate():
    pipeline = ColumnTransformPipeline.from_sensitivity_map({
        "email": "pii",
        "ssn": "pii",
        "card_number": "pci",
    })
    rows = [
        {
            "id": i,
            "email": f"user{i}@example.com",
            "ssn": f"{i:09d}",
            "card_number": "4111111111111111",
        }
        for i in range(_ROW_COUNT)
    ]
    start = time.perf_counter()
    pipeline.apply_batch(rows)
    elapsed = time.perf_counter() - start
    assert elapsed < _MAX_SECONDS, (
        f"Transform throughput regression: {_ROW_COUNT} rows took {elapsed:.2f}s "
        f"(limit {_MAX_SECONDS}s)"
    )
