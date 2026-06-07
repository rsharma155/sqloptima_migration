# Author: Ravi Sharma
# Copyright (c) 2026 Ravi Sharma
# SPDX-License-Identifier: MIT

"""TDD tests for shared/kernel/ddl_identifier.py (L-18).

Contract:
  quote_pg_ident:
  - Wraps any non-empty string in PostgreSQL double-quotes.
  - Escapes embedded double-quote characters by doubling them ("" not \").
  - Raises ValueError on empty string (empty identifiers are invalid SQL).

  validate_sql_identifier:
  - Raises ValueError if name is empty.
  - Raises ValueError if name exceeds 63 characters (PostgreSQL NAMEDATALEN-1).
  - Returns silently for valid identifiers.

  DdlIdentifier value object:
  - Immutable; validated at construction time.
  - .quoted property returns the double-quoted form.
  - Two DdlIdentifiers with the same name compare equal.
"""

from __future__ import annotations

import pytest

from shared.kernel.ddl_identifier import DdlIdentifier, quote_pg_ident, validate_sql_identifier


# ═══════════════════════════════════════════════════════════════════════════
# quote_pg_ident
# ═══════════════════════════════════════════════════════════════════════════

class TestQuotePgIdent:
    def test_simple_lowercase(self):
        assert quote_pg_ident("users") == '"users"'

    def test_simple_uppercase_preserved(self):
        assert quote_pg_ident("Users") == '"Users"'

    def test_underscore_name(self):
        assert quote_pg_ident("my_table") == '"my_table"'

    def test_name_with_space(self):
        assert quote_pg_ident("my table") == '"my table"'

    def test_name_with_hyphen(self):
        assert quote_pg_ident("my-table") == '"my-table"'

    def test_name_with_dot(self):
        # Dots in identifier names (not schema.table separators)
        assert quote_pg_ident("my.table") == '"my.table"'

    def test_name_with_number(self):
        assert quote_pg_ident("table1") == '"table1"'

    def test_schema_name(self):
        assert quote_pg_ident("dbo") == '"dbo"'

    def test_embedded_double_quote_is_escaped(self):
        # " becomes "" inside a quoted identifier
        assert quote_pg_ident('foo"bar') == '"foo""bar"'

    def test_multiple_embedded_quotes(self):
        assert quote_pg_ident('a"b"c') == '"a""b""c"'

    def test_only_double_quote(self):
        assert quote_pg_ident('"') == '""""'

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="empty"):
            quote_pg_ident("")

    def test_unicode_name(self):
        # PostgreSQL allows Unicode identifiers
        assert quote_pg_ident("benutzer") == '"benutzer"'

    def test_sql_injection_attempt_is_quoted_safely(self):
        # The injection string cannot escape the double-quote wrapping
        dangerous = "users; DROP TABLE users; --"
        result = quote_pg_ident(dangerous)
        assert result.startswith('"')
        assert result.endswith('"')
        assert "DROP" in result  # content preserved but safely quoted
        # No unescaped quotes exist outside the wrapping pair
        inner = result[1:-1]
        assert '"' not in inner  # inner " would have been doubled → none remain single


# ═══════════════════════════════════════════════════════════════════════════
# validate_sql_identifier
# ═══════════════════════════════════════════════════════════════════════════

class TestValidateSqlIdentifier:
    def test_valid_simple_name(self):
        validate_sql_identifier("users", "table")  # no exception

    def test_valid_max_length(self):
        validate_sql_identifier("a" * 63, "table")  # exactly 63 — OK

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="empty"):
            validate_sql_identifier("", "table")

    def test_too_long_raises(self):
        with pytest.raises(ValueError, match="63"):
            validate_sql_identifier("a" * 64, "table")

    def test_label_appears_in_error(self):
        with pytest.raises(ValueError, match="schema_name"):
            validate_sql_identifier("", "schema_name")

    def test_none_raises(self):
        with pytest.raises((ValueError, TypeError)):
            validate_sql_identifier(None, "table")  # type: ignore[arg-type]


# ═══════════════════════════════════════════════════════════════════════════
# DdlIdentifier value object
# ═══════════════════════════════════════════════════════════════════════════

class TestDdlIdentifier:
    def test_quoted_returns_double_quoted_form(self):
        ident = DdlIdentifier("users")
        assert ident.quoted == '"users"'

    def test_str_returns_raw_name(self):
        ident = DdlIdentifier("my_table")
        assert str(ident) == "my_table"

    def test_equality_by_value(self):
        assert DdlIdentifier("orders") == DdlIdentifier("orders")

    def test_inequality_different_names(self):
        assert DdlIdentifier("orders") != DdlIdentifier("ORDERS")

    def test_empty_name_raises_at_construction(self):
        with pytest.raises(ValueError):
            DdlIdentifier("")

    def test_too_long_name_raises_at_construction(self):
        with pytest.raises(ValueError):
            DdlIdentifier("x" * 64)

    def test_embedded_quote_escaped_in_quoted(self):
        ident = DdlIdentifier('weird"name')
        assert ident.quoted == '"weird""name"'

    def test_hashable(self):
        # Value objects should be usable as dict keys / in sets
        s = {DdlIdentifier("a"), DdlIdentifier("b"), DdlIdentifier("a")}
        assert len(s) == 2

    def test_repr_includes_name(self):
        ident = DdlIdentifier("orders")
        assert "orders" in repr(ident)


# ═══════════════════════════════════════════════════════════════════════════
# Integration: quote_pg_ident applied in a DDL string
# ═══════════════════════════════════════════════════════════════════════════

class TestDdlStringConstruction:
    def test_schema_qualified_table_quoted(self):
        schema = quote_pg_ident("dbo")
        table = quote_pg_ident("Order Details")  # space in name
        ddl = f"CREATE TABLE {schema}.{table} (id INTEGER);"
        assert ddl == 'CREATE TABLE "dbo"."Order Details" (id INTEGER);'

    def test_injection_in_schema_is_neutralised(self):
        malicious_schema = 'public"; DROP TABLE users; --'
        schema = quote_pg_ident(malicious_schema)
        ddl = f"CREATE TABLE {schema}.users (id INTEGER);"
        # The semicolon and DROP are inside the quoted identifier — not executable
        assert 'DROP TABLE users' in ddl  # content exists
        assert ddl.startswith('CREATE TABLE "')  # but safely wrapped
        # The parser would see the whole malicious string as ONE identifier name
        assert ddl.count('"') == 4  # two pairs: schema open/close, table open/close
