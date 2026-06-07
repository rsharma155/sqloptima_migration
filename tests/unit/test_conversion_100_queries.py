"""
Module: test_conversion_100_queries.py
Purpose: Validate 100 T-SQL -> PostgreSQL conversions by comparing converter
         output against expected results in the fixture file.
         
The fixture files are:
  - tests/fixtures/sqlserver_queires_input.sql       (100 T-SQL queries)
  - tests/fixtures/postgres_converted_sqlserver_queries.sql  (expected PG outputs)

To regenerate the expected file:
  python tests/fixtures/generate_converted_queries.py
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

import re
from pathlib import Path

import pytest

from domains.transpilation.procedural_converter import ProceduralConverter

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"
INPUT_FILE = FIXTURE_DIR / "sqlserver_queires_input.sql"
EXPECTED_FILE = FIXTURE_DIR / "postgres_converted_sqlserver_queries.sql"

SKIP_LIST: set[str] = set()
"""
Skip labels for conversions known to produce different output on each run
or that are inherently non-deterministic. Add a label like '#42' to skip it.
"""


def _parse_numbered_file(path: Path) -> list[tuple[str, str]]:
    """Parse a file with #N prefix lines into list of (label, text) pairs."""
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    blocks = re.split(r'^(#\d+)\s+', content, flags=re.MULTILINE)
    items: list[tuple[str, str]] = []
    i = 1
    while i < len(blocks) - 1:
        label = blocks[i].strip()
        body = blocks[i + 1].strip().rstrip(";")
        if body and not body.startswith("--"):
            items.append((label, body))
        i += 2
    return items


def _normalize(sql: str) -> str:
    """Collapse whitespace for comparison."""
    return re.sub(r'\s+', ' ', sql).strip().rstrip(";")


@pytest.fixture(scope="session")
def converter():
    return ProceduralConverter()


@pytest.fixture(scope="session")
def input_queries():
    return _parse_numbered_file(INPUT_FILE)


@pytest.fixture(scope="session")
def expected_queries():
    return _parse_numbered_file(EXPECTED_FILE)


def test_all_queries_present(input_queries, expected_queries):
    """Verify both files have the same numbered entries."""
    input_labels = {lb for lb, _ in input_queries}
    expected_labels = {lb for lb, _ in expected_queries}
    assert input_labels == expected_labels, (
        f"Label mismatch. Missing in expected: {input_labels - expected_labels}. "
        f"Missing in input: {expected_labels - input_labels}."
    )


def test_no_duplicate_labels(input_queries, expected_queries):
    """Verify no duplicate #N labels in either file."""
    for label, items in [("input", input_queries), ("expected", expected_queries)]:
        labels = [lb for lb, _ in items]
        dups = {lb for lb in labels if labels.count(lb) > 1}
        assert not dups, f"Duplicate labels in {label} file: {dups}"


@pytest.mark.parametrize(
    "label,input_sql,expected_sql",
    [
        (label, sql, expected)
        for (label, sql), (_, expected) in zip(
            _parse_numbered_file(INPUT_FILE),
            _parse_numbered_file(EXPECTED_FILE),
        )
        if label not in SKIP_LIST
    ],
    ids=lambda x: x if isinstance(x, str) and x.startswith("#") else "",
)
def test_conversion(label, input_sql, expected_sql, converter):
    """Converter output for each T-SQL query must match the expected PG output."""
    result = converter.auto_convert(input_sql)
    assert result.success, f"{label}: conversion failed: {'; '.join(result.errors)}"

    actual = _normalize(result.converted_sql)
    expected = _normalize(expected_sql)

    assert actual == expected, (
        f"{label}: output mismatch\n"
        f"  expected: {expected_sql}\n"
        f"  actual:   {result.converted_sql}"
    )
