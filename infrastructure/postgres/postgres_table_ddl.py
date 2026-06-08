"""
Module: postgres_table_ddl.py
Purpose: Reconstruct readable PostgreSQL CREATE TABLE DDL from catalog rows.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

from shared.kernel.ddl_identifier import quote_pg_ident

_INLINE_CONSTRAINT_TYPES = frozenset({"p", "u", "c"})


def assemble_postgres_table_definition(
    schema_name: str,
    table_name: str,
    *,
    column_defs: list[str],
    constraints: list[dict[str, str]],
    secondary_indexes: list[str],
) -> str:
    """Build CREATE TABLE DDL without duplicate PK/UNIQUE index statements.

    PostgreSQL stores PRIMARY KEY and UNIQUE constraints as backing indexes.
    Those indexes must not be emitted separately when the constraint is already
    represented inline in CREATE TABLE.
    """
    qualified = f"{quote_pg_ident(schema_name)}.{quote_pg_ident(table_name)}"
    body_parts = list(column_defs)

    inline_constraints: list[str] = []
    foreign_keys: list[str] = []
    for con in constraints:
        contype = con.get("contype", "")
        conname = con.get("conname", "")
        condef = con.get("condef", "")
        if not conname or not condef:
            continue
        line = f'    CONSTRAINT {quote_pg_ident(conname)} {condef}'
        if contype in _INLINE_CONSTRAINT_TYPES:
            inline_constraints.append(line)
        elif contype == "f":
            foreign_keys.append(
                f"\nALTER TABLE {qualified} "
                f"ADD CONSTRAINT {quote_pg_ident(conname)} {condef};"
            )

    body_parts.extend(inline_constraints)
    definition = f"CREATE TABLE {qualified} (\n" + ",\n".join(body_parts) + "\n);\n"

    for indexdef in secondary_indexes:
        if indexdef:
            definition += f"\n{indexdef};"

    definition += "".join(foreign_keys)
    return definition
