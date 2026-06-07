"""Test PostgreSQL connection with various methods
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
import asyncio
import asyncpg

async def test():
    attempts = [
        {"host": "localhost", "port": 30432, "user": "postgres", "password": "postgres123", "database": "postgres"},
        {"host": "localhost", "port": 30432, "user": "postgres", "password": "postgres", "database": "postgres"},
        {"host": "localhost", "port": 30432, "user": "postgres", "password": "", "database": "postgres"},
        {"host": "127.0.0.1", "port": 30432, "user": "postgres", "password": "postgres123", "database": "postgres"},
        {"host": "localhost", "port": 5432, "user": "postgres", "password": "postgres123", "database": "postgres"},
    ]
    for i, params in enumerate(attempts):
        try:
            print(f"Attempt {i+1}: {params['host']}:{params['port']} user={params['user']} db={params['database']}")
            conn = await asyncpg.connect(**params)
            v = await conn.fetchval("SELECT version()")
            print(f"  SUCCESS: {v}")
            await conn.close()
            return params
        except Exception as e:
            print(f"  FAILED: {e}")
    return None

result = asyncio.run(test())
if result:
    print(f"\nWorking config: {result}")
else:
    print("\nNo working PostgreSQL connection found")
