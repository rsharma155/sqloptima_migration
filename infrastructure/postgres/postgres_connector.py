"""
Module: postgres_connector.py
Purpose: PostgreSQL database adapter (asyncpg)
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
from __future__ import annotations

from typing import Any
from uuid import uuid4

import asyncpg

from shared.contracts.base_connector import ConnectionConfig, DatabaseConnector
from shared.contracts.config_validation import validate_pool_bounds
from shared.kernel.ddl_identifier import quote_pg_ident
from shared.logging.structured_logging import get_logger

logger = get_logger(__name__)

# Fix 9.3: module-level constant so tests can import it.
COPY_BATCH_SIZE: int = 5_000


class PostgresConnectionConfig(ConnectionConfig):
    def __init__(
        self,
        host: str,
        port: int,
        database: str,
        username: str,
        password: str,
        schema: str | None = None,
        extra_params: dict | None = None,
        min_pool_size: int = 2,
        max_pool_size: int = 20,
        # Per-statement timeout (seconds). Caps how long a single query may run so a
        # slow/runaway statement cannot hold a pooled connection forever (Issue #16).
        statement_timeout_seconds: float = 30.0,
        # SSL mode for the PostgreSQL connection.
        # Fix 8.2: default to "require" (enforce TLS).  Override to None only for
        # local development where no TLS is configured.
        # Accepted values: "require", "verify-ca", "verify-full", None (disable enforcement).
        ssl_mode: str | None = "require",
    ) -> None:
        super().__init__(host=host, port=port, database=database, username=username, password=password, schema=schema, extra_params=extra_params)
        self.min_pool_size = min_pool_size
        self.max_pool_size = max_pool_size
        self.statement_timeout_seconds = statement_timeout_seconds
        self.ssl_mode = ssl_mode

    @property
    def connection_string(self) -> str:
        return (
            f"postgresql://{self.username}:{self.password}"
            f"@{self.host}:{self.port}/{self.database}"
        )

    @property
    def dsn(self) -> str:
        return (
            f"postgresql://{self.username}@"
            f"{self.host}:{self.port}/{self.database}"
        )


class PostgresConnector(DatabaseConnector):
    def __init__(self, config: PostgresConnectionConfig):
        self._config = config
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        if self._pool is not None:
            return
        # Reject nonsensical pool bounds before any network I/O so the operator
        # gets a clear error instead of a late driver-level failure (Issue #27).
        validate_pool_bounds(self._config.min_pool_size, self._config.max_pool_size)
        pool_kwargs: dict = dict(
            host=self._config.host,
            port=self._config.port,
            user=self._config.username,
            password=self._config.password,
            database=self._config.database,
            min_size=self._config.min_pool_size,
            max_size=self._config.max_pool_size,
        )
        if self._config.ssl_mode is not None:
            pool_kwargs["ssl"] = self._config.ssl_mode
        else:
            logger.warning(
                "postgres_tls_not_enforced",
                host=self._config.host,
                message=(
                    "ssl_mode is not set — connection will fall back to plaintext if the "
                    "PostgreSQL server does not require SSL. Set ssl_mode='require' (or "
                    "'verify-full') in production to enforce encryption."
                ),
            )
        self._pool = await asyncpg.create_pool(**pool_kwargs)

    async def disconnect(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def execute(self, query: str, *args: Any) -> list[dict[str, Any]]:
        """Execute a query and return rows as dicts.

        Fix 6.2: asyncpg uses positional $1/$2/… placeholders; the old dict-based
        params were order-dependent and silently broke when callers constructed
        the dict in a different order.  Now accepts plain *args so callers pass
        values in the same order as the $1/$2/… markers in the query.
        """
        if not self._pool:
            raise RuntimeError("Not connected. Call connect() first.")
        timeout = self._config.statement_timeout_seconds
        async with self._pool.acquire() as conn:
            if args:
                records = await conn.fetch(query, *args, timeout=timeout)
            else:
                records = await conn.fetch(query, timeout=timeout)
            if records:
                columns = list(records[0].keys())
                return [dict(zip(columns, row.values(), strict=False)) for row in records]
            return []

    async def execute_many(self, query: str, params_list: list) -> None:
        if not self._pool:
            raise RuntimeError("Not connected. Call connect() first.")
        if not params_list:
            return
        # Accept both list[dict] and list[tuple/list]
        if params_list and isinstance(params_list[0], dict):
            args_list = [tuple(p.values()) for p in params_list]
        else:
            args_list = [tuple(p) for p in params_list]
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.executemany(query, args_list)

    async def copy_from_rows(
        self,
        table: str,
        columns: list[str],
        rows: list[tuple],
        schema: str | None = None,
        batch_size: int = COPY_BATCH_SIZE,
        sub_batch_size: int | None = None,
    ) -> int:
        """Copy rows using asyncpg binary COPY protocol.

        Fix 9.3: when ``rows`` exceeds ``sub_batch_size`` the data is sent in
        multiple COPY calls so asyncpg never builds a single massive binary buffer.
        Each sub-batch runs in its own connection acquisition but shares no
        transaction with other batches (each sub-batch is atomic on its own).
        """
        if not self._pool:
            raise RuntimeError("Not connected.")
        if not rows:
            return 0

        # sub_batch_size is a legacy alias; batch_size always wins.
        if sub_batch_size is not None:
            batch_size = sub_batch_size
        total = 0
        for i in range(0, len(rows), batch_size):
            sub = rows[i : i + batch_size]
            async with self._pool.acquire() as conn:
                await conn.copy_records_to_table(
                    table_name=table,
                    columns=columns,
                    records=sub,
                    schema_name=schema,
                )
            total += len(sub)
        return total

    async def copy_with_idempotent_write(
        self,
        table: str,
        columns: list[str],
        rows: list[tuple],
        schema: str | None = None,
        conflict_columns: list[str] | None = None,
    ) -> int:
        if not rows:
            return 0
        # Use quote_pg_ident so embedded " chars in schema/table names are escaped.
        resolved_schema = f"{quote_pg_ident(schema)}." if schema else ""
        quoted_table = quote_pg_ident(table)
        staging_table = f"_mig_staging_{uuid4().hex[:8]}"  # internal name, hex only — safe
        quoted_cols = ", ".join(quote_pg_ident(c) for c in columns)

        conflict_cols = ", ".join(
            quote_pg_ident(c) for c in (conflict_columns or [columns[0]])
        )
        update_set = ", ".join(
            f"{quote_pg_ident(c)} = EXCLUDED.{quote_pg_ident(c)}" for c in columns
        )

        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute(f"""
                CREATE TEMP TABLE {staging_table} (
                    LIKE {resolved_schema}{quoted_table}
                ) ON COMMIT DROP
            """)
            await conn.copy_records_to_table(
                table_name=staging_table,
                columns=columns,
                records=rows,
            )
            merge_sql = f"""
                INSERT INTO {resolved_schema}{quoted_table} ({quoted_cols})
                SELECT {quoted_cols} FROM {staging_table}
                ON CONFLICT ({conflict_cols})
                DO UPDATE SET {update_set}
            """
            await conn.execute(merge_sql)
            return len(rows)

    @property
    def pool(self) -> asyncpg.Pool | None:
        return self._pool
