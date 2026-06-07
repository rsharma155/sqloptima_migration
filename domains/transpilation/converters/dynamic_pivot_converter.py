"""
Module: domains/transpilation/converters/dynamic_pivot_converter.py
Purpose: Converts dynamic T-SQL PIVOT (where column values come from a subquery)
         to a PL/pgSQL DO $$ ... EXECUTE v_sql; END $$ block that uses
         STRING_AGG to build the column list at runtime.

         Static PIVOT (column values known at parse time) continues to be handled
         by StaticPivotRewriter in pivot_converter.py using CASE WHEN aggregation.
         Dynamic PIVOT — previously outputting NULL placeholders — is now handled here.

Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations


class DynamicPivotConverter:
    """Converts dynamic T-SQL PIVOT to PL/pgSQL EXECUTE with dynamic column list.

    The generated DO block:
    1. Queries DISTINCT values of the pivot column to build the SELECT list via
       STRING_AGG and FORMAT.
    2. Constructs a dynamic SQL string for the full pivoted query.
    3. EXECUTEs the dynamic SQL.

    Usage::

        converter = DynamicPivotConverter()
        plpgsql = converter.convert(
            agg_func="SUM",
            pivot_col="category",
            value_col="amount",
            source_table="sales",
            group_col="region",
        )
    """

    def convert(
        self,
        agg_func: str,
        pivot_col: str,
        value_col: str,
        source_table: str,
        group_col: str,
    ) -> str:
        """Generate a DO $$ ... END $$ block for a dynamic PIVOT.

        Parameters
        ----------
        agg_func:
            Aggregate function name, e.g. ``'SUM'``, ``'AVG'``, ``'MAX'``.
        pivot_col:
            The column whose DISTINCT values become the output columns.
        value_col:
            The column being aggregated for each pivot value.
        source_table:
            The source table (or subquery alias) to query.
        group_col:
            The column(s) to GROUP BY in the outer query (non-pivot dimension).

        Returns
        -------
        str
            A PL/pgSQL DO block as a string.
        """
        return (
            f"DO $$\n"
            f"DECLARE\n"
            f"    v_cols TEXT;\n"
            f"    v_sql  TEXT;\n"
            f"BEGIN\n"
            f"    SELECT STRING_AGG(\n"
            f"        FORMAT(\n"
            f"            '{agg_func}(CASE WHEN {pivot_col} = %L THEN {value_col} END) AS %I',\n"
            f"            {pivot_col}, {pivot_col}\n"
            f"        ),\n"
            f"        ', '\n"
            f"    ) INTO v_cols\n"
            f"    FROM (SELECT DISTINCT {pivot_col} FROM {source_table}) t;\n"
            f"    v_sql := FORMAT(\n"
            f"        'SELECT {group_col}, %s FROM {source_table} GROUP BY {group_col}',\n"
            f"        v_cols\n"
            f"    );\n"
            f"    EXECUTE v_sql;\n"
            f"END $$;"
        )
