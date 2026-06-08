"""Unit tests for PostgreSQL table DDL reconstruction."""

from __future__ import annotations

from infrastructure.postgres.postgres_table_ddl import assemble_postgres_table_definition


def test_primary_key_is_inline_without_duplicate_unique_index():
    ddl = assemble_postgres_table_definition(
        "public",
        "Hotels",
        column_defs=[
            "    HotelID integer NOT NULL",
            "    HotelName character varying",
        ],
        constraints=[
            {
                "conname": "Hotels_pkey",
                "contype": "p",
                "condef": 'PRIMARY KEY ("HotelID")',
            }
        ],
        secondary_indexes=[],
    )

    assert 'CONSTRAINT "Hotels_pkey" PRIMARY KEY ("HotelID")' in ddl
    assert "CREATE UNIQUE INDEX" not in ddl
    assert "ALTER TABLE" not in ddl


def test_unique_constraint_is_inline_without_duplicate_index():
    ddl = assemble_postgres_table_definition(
        "public",
        "Users",
        column_defs=["    email character varying NOT NULL"],
        constraints=[
            {
                "conname": "Users_email_key",
                "contype": "u",
                "condef": 'UNIQUE ("email")',
            }
        ],
        secondary_indexes=[],
    )

    assert 'CONSTRAINT "Users_email_key" UNIQUE ("email")' in ddl
    assert "CREATE UNIQUE INDEX" not in ddl


def test_secondary_indexes_and_foreign_keys_are_appended():
    ddl = assemble_postgres_table_definition(
        "public",
        "Orders",
        column_defs=["    id integer NOT NULL"],
        constraints=[
            {
                "conname": "Orders_pkey",
                "contype": "p",
                "condef": 'PRIMARY KEY ("id")',
            },
            {
                "conname": "Orders_customer_id_fkey",
                "contype": "f",
                "condef": 'FOREIGN KEY ("customer_id") REFERENCES "Customers" ("id")',
            },
        ],
        secondary_indexes=[
            'CREATE INDEX "Orders_created_at_idx" ON public."Orders" USING btree ("created_at")',
        ],
    )

    assert 'CREATE INDEX "Orders_created_at_idx"' in ddl
    assert 'ADD CONSTRAINT "Orders_customer_id_fkey" FOREIGN KEY' in ddl
    assert "CREATE UNIQUE INDEX" not in ddl
