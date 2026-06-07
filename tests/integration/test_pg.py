"""Test PostgreSQL connection with corrected password
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
import asyncio
import asyncpg

async def test():
    params = {"host": "localhost", "port": 30432, "user": "postgres", "password": "Hello@123", "database": "postgres"}
    try:
        conn = await asyncpg.connect(**params)
        v = await conn.fetchval("SELECT version()")
        print(f"SUCCESS: {v}")

        dbs = await conn.fetch(
            "SELECT datname FROM pg_database WHERE datname NOT IN ($1, $2, $3)",
            "postgres", "template0", "template1"
        )
        print(f"Databases: {[r[0] for r in dbs]}")

        if "adventureworks2025" not in [r[0] for r in dbs]:
            await conn.execute("CREATE DATABASE adventureworks2025")
            print("Created database: adventureworks2025")
        else:
            print("Database adventureworks2025 already exists")

        await conn.close()
        print("\nPostgreSQL: CONNECTION OK")
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        return False

asyncio.run(test())
