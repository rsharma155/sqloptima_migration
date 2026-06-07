"""
Module: schema_relabeler.py
Purpose: Manages schema remapping for SQL Server to PostgreSQL migration.
         By default, 'dbo' maps to 'public'.
Domain: Transpilation
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""


class SchemaRelabeler:
    """Manages schema name remapping during migration.

    By default, maps 'dbo' -> 'public' (SQL Server's default to PostgreSQL's default).
    Supports custom remapping via configuration.

    Usage:
        relabeler = SchemaRelabeler()
        relabeler.add_remapping("sales", "sales_new")
        pg_schema = relabeler.relabel("dbo")  # -> "public"
        pg_schema = relabeler.relabel("sales")  # -> "sales_new"
    """

    DEFAULT_REMAPPING: dict[str, str] = {
        "dbo": "public",
    }

    def __init__(self, use_default_dbo_mapping: bool = True):
        self._remappings: dict[str, str] = {}
        self._use_default = use_default_dbo_mapping
        if use_default_dbo_mapping:
            self._remappings.update(self.DEFAULT_REMAPPING)

    def add_remapping(self, source_schema: str, target_schema: str) -> None:
        """Add a single schema remapping rule.

        Overrides the default dbo->public mapping if 'dbo' is passed.
        """
        self._remappings[source_schema.lower()] = target_schema

    def add_remappings(self, mappings: dict[str, str]) -> None:
        """Add multiple schema remapping rules.

        Each key is a source schema, each value is the target schema.
        """
        for source, target in mappings.items():
            self._remappings[source.lower()] = target

    def parse_remapping_string(self, mapping_str: str) -> None:
        """Parse a remapping string in the format 'source1=>dest1;source2=>dest2'.

        This mirrors the -relabel_schemas option from sqlserver2pgsql.
        """
        if not mapping_str:
            return
        pairs = mapping_str.split(";")
        for pair in pairs:
            pair = pair.strip()
            if "=>" not in pair:
                continue
            parts = pair.split("=>", 1)
            source = parts[0].strip().lower()
            target = parts[1].strip()
            if source and target:
                self._remappings[source] = target

    def relabel(self, schema_name: str) -> str:
        """Relabel a schema name using configured remapping rules.

        If no mapping matches, returns the original schema name unchanged.
        """
        if not schema_name:
            return schema_name
        key = schema_name.lower()
        return self._remappings.get(key, schema_name)

    def disable_default_dbo(self) -> None:
        """Remove the default dbo->public mapping.

        Equivalent to the -nr flag in sqlserver2pgsql.
        """
        self._remappings.pop("dbo", None)
        self._use_default = False

    def clear_all(self) -> None:
        """Clear all remapping rules."""
        self._remappings.clear()
        self._use_default = False

    @property
    def mappings(self) -> dict[str, str]:
        """Return a copy of current remapping rules."""
        return self._remappings.copy()

    def __repr__(self) -> str:
        rules = "; ".join(f"{k}=>{v}" for k, v in self._remappings.items())
        return f"SchemaRelabeler({rules})"
