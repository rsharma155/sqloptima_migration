"""Test database connections and explore AdventureWorks2025
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
import asyncio
import pyodbc
import asyncpg

def test_sqlserver():
    """Test SQL Server connection and list objects"""
    print("=" * 60)
    print("TESTING SQL SERVER CONNECTION")
    print("=" * 60)
    try:
        conn = pyodbc.connect(
            "DRIVER={ODBC Driver 18 for SQL Server};"
            "SERVER=ANURAVPC,1433;"
            "DATABASE=master;"
            "UID=sa;PWD=Hello@123;"
            "TrustServerCertificate=yes;"
        )
        cursor = conn.cursor()
        cursor.execute("SELECT @@VERSION")
        row = cursor.fetchone()
        print(f"Version: {row[0][:80]}...")

        cursor.execute("SELECT name FROM sys.databases WHERE state = 0 ORDER BY name")
        dbs = [r[0] for r in cursor.fetchall()]
        print(f"Databases: {dbs}")

        # Check if AdventureWorks2025 exists
        if "AdventureWorks2025" in dbs:
            conn.close()
            conn = pyodbc.connect(
                "DRIVER={ODBC Driver 18 for SQL Server};"
                "SERVER=ANURAVPC,1433;"
                "DATABASE=AdventureWorks2025;"
                "UID=sa;PWD=Hello@123;"
                "TrustServerCertificate=yes;"
            )
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'BASE TABLE'")
            table_count = cursor.fetchone()[0]
            print(f"Tables: {table_count}")

            cursor.execute("SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'VIEW'")
            view_count = cursor.fetchone()[0]
            print(f"Views: {view_count}")

            cursor.execute("SELECT COUNT(*) FROM INFORMATION_SCHEMA.ROUTINES WHERE ROUTINE_TYPE = 'PROCEDURE'")
            proc_count = cursor.fetchone()[0]
            print(f"Procedures: {proc_count}")

            cursor.execute("SELECT COUNT(*) FROM INFORMATION_SCHEMA.ROUTINES WHERE ROUTINE_TYPE = 'FUNCTION'")
            func_count = cursor.fetchone()[0]
            print(f"Functions: {func_count}")

            cursor.execute("SELECT TABLE_SCHEMA, TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'BASE TABLE' ORDER BY TABLE_SCHEMA, TABLE_NAME")
            tables = cursor.fetchall()
            print(f"\nAll Tables ({len(tables)}):")
            for t in tables:
                print(f"  {t[0]}.{t[1]}")

            cursor.execute("SELECT TABLE_SCHEMA, TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'VIEW' ORDER BY TABLE_SCHEMA, TABLE_NAME")
            views = cursor.fetchall()
            print(f"\nAll Views ({len(views)}):")
            for v in views:
                print(f"  {v[0]}.{v[1]}")

            cursor.execute("SELECT SPECIFIC_SCHEMA, SPECIFIC_NAME FROM INFORMATION_SCHEMA.ROUTINES WHERE ROUTINE_TYPE = 'PROCEDURE' ORDER BY SPECIFIC_SCHEMA, SPECIFIC_NAME")
            procs = cursor.fetchall()
            print(f"\nAll Procedures ({len(procs)}):")
            for p in procs:
                print(f"  {p[0]}.{p[1]}")

            cursor.execute("SELECT SPECIFIC_SCHEMA, SPECIFIC_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.ROUTINES WHERE ROUTINE_TYPE = 'FUNCTION' ORDER BY SPECIFIC_SCHEMA, SPECIFIC_NAME")
            funcs = cursor.fetchall()
            print(f"\nAll Functions ({len(funcs)}):")
            for f in funcs:
                print(f"  {f[0]}.{f[1]} ({f[2]})")

            # Check constraints
            cursor.execute("SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS")
            constraint_count = cursor.fetchone()[0]
            print(f"\nConstraints: {constraint_count}")

            cursor.execute("SELECT CONSTRAINT_TYPE, COUNT(*) FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS GROUP BY CONSTRAINT_TYPE")
            for row in cursor.fetchall():
                print(f"  {row[0]}: {row[1]}")

        conn.close()
        print("\nSQL Server: CONNECTION OK")
        return True
    except Exception as e:
        print(f"\nSQL Server ERROR: {e}")
        return False


async def test_postgres():
    """Test PostgreSQL connection"""
    print("\n" + "=" * 60)
    print("TESTING POSTGRESQL CONNECTION")
    print("=" * 60)
    try:
        conn = await asyncpg.connect(
            host="localhost",
            port=30432,
            user="postgres",
            password="postgres123",
            database="postgres"
        )
        v = await conn.fetchval("SELECT version()")
        print(f"Version: {v}")

        dbs = await conn.fetch(
            "SELECT datname FROM pg_database WHERE datname NOT IN ($1, $2, $3)",
            "postgres", "template0", "template1"
        )
        print(f"Databases: {[r[0] for r in dbs]}")

        # Try creating adventureworks2025 if it doesn't exist
        if "adventureworks2025" not in [r[0] for r in dbs]:
            await conn.execute("CREATE DATABASE adventureworks2025")
            print("Created database: adventureworks2025")
        else:
            print("Database adventureworks2025 already exists")

        await conn.close()
        print("\nPostgreSQL: CONNECTION OK")
        return True
    except Exception as e:
        print(f"\nPostgreSQL ERROR: {e}")
        return False


if __name__ == "__main__":
    test_sqlserver()
    result = asyncio.run(test_postgres())
