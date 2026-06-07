"""Live dual-DB procedure/query equivalence tests (§11.2).

Set MIGRATION_E2E_PROC_EQ=1 and configure:
  MIGRATION_SOURCE_HOST/PORT/DATABASE/USER/PASSWORD
  MIGRATION_TARGET_HOST/PORT/DATABASE/USER/PASSWORD
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("MIGRATION_E2E_PROC_EQ") != "1",
    reason="Set MIGRATION_E2E_PROC_EQ=1 with source/target env vars",
)


@pytest.mark.asyncio
async def test_live_query_equivalence_corpus():
    from domains.validation.query_equivalence_harness import (
        QueryEquivalenceCase,
        QueryEquivalenceHarness,
        build_connectors_from_env,
    )

    corpus_path = Path(__file__).parents[1] / "fixtures" / "query_equivalence_corpus.json"
    cases = [
        QueryEquivalenceCase(**c)
        for c in json.loads(corpus_path.read_text())["cases"]
    ]
    source, target = await build_connectors_from_env()
    try:
        harness = QueryEquivalenceHarness(source, target)
        results = await harness.run_corpus(cases)
        failed = [r for r in results if not r.passed]
        assert not failed, f"Query equivalence failures: {[f.case_name for f in failed]}"
    finally:
        await source.disconnect()
        await target.disconnect()


@pytest.mark.asyncio
async def test_live_procedure_equivalence_corpus():
    from domains.validation.procedure_equivalence_harness import (
        ProcedureEquivalenceHarness,
        load_corpus,
    )
    from domains.validation.query_equivalence_harness import build_connectors_from_env

    corpus_path = Path(__file__).parents[1] / "fixtures" / "procedure_equivalence_corpus.json"
    cases = [c for c in load_corpus(corpus_path) if not c.skip_runtime]
    if not cases:
        pytest.skip("No runtime procedure cases in corpus")

    source, target = await build_connectors_from_env()
    try:
        harness = ProcedureEquivalenceHarness(source, target)
        results = await harness.run_corpus(cases, deploy=True)
        failed = [r for r in results if not r.passed]
        assert not failed, f"Procedure equivalence failures: {[f.case_name for f in failed]}"
    finally:
        await source.disconnect()
        await target.disconnect()
