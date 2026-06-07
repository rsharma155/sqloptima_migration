"""End-to-end golden data-integrity test (§11.1).

Set MIGRATION_E2E_INTEGRITY=1 with docker-compose sample-dbs running.
"""
from __future__ import annotations

import os

import pytest

from tests.e2e.golden_integrity import (
    assert_parity,
    fetch_target_rows,
    migrate_table,
    setup_source,
    setup_target,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("MIGRATION_E2E_INTEGRITY") != "1",
    reason="Set MIGRATION_E2E_INTEGRITY=1 and start docker-compose to run",
)


@pytest.mark.asyncio
async def test_golden_dataset_row_count_parity():
    from domains.validation.query_equivalence_harness import build_connectors_from_env

    source, target = await build_connectors_from_env()
    try:
        await source.connect()
        await target.connect()
        await setup_source(source)
        await setup_target(target)
        source_rows = await source.execute(
            "SELECT id, name, amount FROM dbo.golden_e2e ORDER BY id"
        )
        migrated = await migrate_table(source, target)
        assert migrated == len(source_rows)
        target_rows = await fetch_target_rows(target)
        assert_parity(source_rows, target_rows)
    finally:
        await source.disconnect()
        await target.disconnect()
