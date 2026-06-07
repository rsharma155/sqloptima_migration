"""Golden dataset setup + migrate + verify helpers (§11.1)."""
from __future__ import annotations

from typing import Any

TABLE = "golden_e2e"
SCHEMA_SRC = "dbo"
SCHEMA_TGT = "public"
COLUMNS = ["id", "name", "amount"]


async def setup_source(source: Any) -> None:
    await source.execute(
        f"IF OBJECT_ID('{SCHEMA_SRC}.{TABLE}', 'U') IS NOT NULL "
        f"DROP TABLE [{SCHEMA_SRC}].[{TABLE}];"
    )
    await source.execute(f"""
        CREATE TABLE [{SCHEMA_SRC}].[{TABLE}] (
            id INT NOT NULL PRIMARY KEY,
            name NVARCHAR(100) NULL,
            amount DECIMAL(18, 2) NULL
        );
    """)
    await source.execute(f"""
        INSERT INTO [{SCHEMA_SRC}].[{TABLE}] (id, name, amount) VALUES
        (1, N'alice', 10.50),
        (2, N'bob', NULL),
        (3, N'charlie', 0.01);
    """)


async def setup_target(target: Any) -> None:
    await target.execute(f"DROP TABLE IF EXISTS {SCHEMA_TGT}.{TABLE};")
    await target.execute(f"""
        CREATE TABLE {SCHEMA_TGT}.{TABLE} (
            id INT PRIMARY KEY,
            name TEXT,
            amount DECIMAL(18, 2)
        );
    """)


async def migrate_table(source: Any, target: Any) -> int:
    from domains.migration.migration_engine import DataExtractor, DataLoader

    rows = await source.execute(
        f"SELECT id, name, amount FROM [{SCHEMA_SRC}].[{TABLE}] ORDER BY id"
    )
    tuples = [tuple(r[c] for c in COLUMNS) for r in rows]
    loader = DataLoader(target, idempotent=True, conflict_columns=["id"])
    return await loader.load_chunk(SCHEMA_TGT, TABLE, COLUMNS, tuples)


async def fetch_target_rows(target: Any) -> list[dict]:
    return await target.execute(
        f"SELECT id, name, amount FROM {SCHEMA_TGT}.{TABLE} ORDER BY id"
    )


def assert_parity(source_rows: list[dict], target_rows: list[dict]) -> None:
    assert len(source_rows) == len(target_rows), (
        f"row count mismatch: source={len(source_rows)} target={len(target_rows)}"
    )
    for src, tgt in zip(source_rows, target_rows):
        assert src["id"] == tgt["id"]
        assert (src.get("name") or None) == (tgt.get("name") or None)
        s_amt = float(src["amount"]) if src.get("amount") is not None else None
        t_amt = float(tgt["amount"]) if tgt.get("amount") is not None else None
        assert s_amt == t_amt, f"id={src['id']}: amount {s_amt} != {t_amt}"
