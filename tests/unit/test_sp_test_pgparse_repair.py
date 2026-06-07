"""
Benchmark pgparse validation pass rate on SP_test corpora after repair loop.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from application.conversion_service import ConversionRequest, ConversionService

SP_DIRS = [
    Path("SP_test/sqlserver"),
    Path("SP_test/sqlserver_newSPs"),
]


def _collect_sp_files() -> list[Path]:
    files: list[Path] = []
    for directory in SP_DIRS:
        if directory.is_dir():
            files.extend(sorted(directory.glob("*.sql")))
    return files


@pytest.fixture(scope="module")
def sp_files() -> list[Path]:
    files = _collect_sp_files()
    if not files:
        pytest.skip("SP_test SQL files not found")
    return files


class TestSpTestPgparseRepair:
    def test_sp_corpus_pgparse_pass_rate(self, sp_files: list[Path]):
        without = ConversionService(enable_repair=False)
        with_repair = ConversionService(enable_repair=True)

        valid_without = 0
        valid_with = 0
        repaired = 0
        for path in sp_files:
            sql = path.read_text(encoding="utf-8", errors="replace")
            req = ConversionRequest(sql=sql, object_type="auto")
            base = without.convert(req)
            fixed = with_repair.convert(req)
            if base.postgres_syntax_valid:
                valid_without += 1
            if fixed.postgres_syntax_valid:
                valid_with += 1
            if fixed.repairs_applied:
                repaired += 1

        total = len(sp_files)
        rate_without = valid_without / total
        rate_with = valid_with / total

        # Baseline ~42%; validator tuning + repair should beat that materially.
        assert rate_without >= 0.44, f"baseline pass rate {rate_without:.1%} unexpectedly low"
        assert rate_with >= 0.48, f"repaired pass rate {rate_with:.1%} below 48% target"
        assert valid_with >= valid_without, "repair must not reduce pgparse pass count"
        assert repaired > 0, "expected auto-repairs on SP_test corpus"

    def test_repair_does_not_break_simple_procedure(self):
        svc = ConversionService(enable_repair=True)
        sql = """
        CREATE PROCEDURE dbo.usp_hello
        AS BEGIN
            SELECT 1;
        END
        """
        result = svc.convert(ConversionRequest(sql=sql, object_type="auto"))
        assert result.success
        assert result.postgres_syntax_valid
        assert "usp_hello" in result.converted_sql

    @pytest.mark.parametrize(
        "filename",
        [
            "007_sqlserver_sp_nested_json_report.sql",
            "006_sqlserver_sp_json_analytics.sql",
        ],
    )
    def test_known_failures_fixed(self, filename: str):
        path = next(
            (directory / filename for directory in SP_DIRS if (directory / filename).exists()),
            None,
        )
        if path is None:
            pytest.skip(f"{filename} not found")

        svc = ConversionService(enable_repair=True)
        result = svc.convert(
            ConversionRequest(sql=path.read_text(encoding="utf-8", errors="replace"), object_type="auto")
        )
        assert result.repairs_applied, f"expected repairs for {filename}"
        assert result.postgres_syntax_valid, (
            f"{filename} pgparse errors: {[e.message for e in result.postgres_syntax_errors]}"
        )
