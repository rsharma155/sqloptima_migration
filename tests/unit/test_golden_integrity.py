"""Unit tests for golden integrity parity assertions (§11.1)."""
from __future__ import annotations

import pytest

from tests.e2e.golden_integrity import assert_parity


def test_assert_parity_matches_rows():
    source = [
        {"id": 1, "name": "alice", "amount": 10.5},
        {"id": 2, "name": None, "amount": None},
    ]
    target = [
        {"id": 1, "name": "alice", "amount": 10.5},
        {"id": 2, "name": None, "amount": None},
    ]
    assert_parity(source, target)


def test_assert_parity_raises_on_count_mismatch():
    with pytest.raises(AssertionError, match="row count mismatch"):
        assert_parity([{"id": 1}], [])
