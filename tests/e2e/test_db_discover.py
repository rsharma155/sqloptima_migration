"""
Test actual database connectivity and discover
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
import json
import urllib.request
import urllib.error
import uuid
import jwt
from datetime import datetime, UTC, timedelta

BASE = "http://localhost:8508"
SECRET = "21sEFmirsqGFkXYqF4Rovoq1PCnGzqk1DGbUkFMaZoQ="
TOKEN = jwt.encode({"sub":"testuser","iat":datetime.now(UTC),"exp":datetime.now(UTC)+timedelta(hours=24)}, SECRET, algorithm="HS256")
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type":"application/json"}

def api(path, method="GET", data=None):
    url = f"{BASE}{path}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=HEADERS, method=method)
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())
    except Exception as e:
        return 0, {"error": str(e)}

print("=" * 70)
print("DATABASE CONNECTION & DISCOVER TESTS")
print("=" * 70)

# 1. Create SQL Server connection
print("\n[1] Creating SQL Server connection...")
s, b = api("/connections", "POST", {
    "name": "SQL-Test", "type": "source",
    "host": "ANURAVPC", "port": 1433,
    "database": "AdventureWorks2025",
    "username": "sa", "password": "Hello@123"
})
sid = b.get("id", "")
print(f"  Status: {s}, ID: {sid}")

# 2. Test SQL Server connection
print("\n[2] Testing SQL Server connection...")
s, b = api(f"/connections/{sid}/test", "POST")
print(f"  Status: {s}")
print(f"  Result: {b.get('status')} - {b.get('message', '')[:200]}")

# 3. Create PostgreSQL connection
print("\n[3] Creating PostgreSQL connection...")
s, b = api("/connections", "POST", {
    "name": "PG-Test", "type": "target",
    "host": "localhost", "port": 30432,
    "database": "postgres",
    "username": "postgres", "password": "Hello@123"
})
pid = b.get("id", "")
print(f"  Status: {s}, ID: {pid}")

# 4. Test PostgreSQL connection
print("\n[4] Testing PostgreSQL connection...")
s, b = api(f"/connections/{pid}/test", "POST")
print(f"  Status: {s}")
print(f"  Result: {b.get('status')} - {b.get('message', '')[:200]}")

# 5. Try discover on SQL Server
print("\n[5] Trying discover on SQL Server (AdventureWorks2025, dbo schema)...")
s, b = api("/discover", "POST", {
    "connection_id": sid,
    "connection_type": "source",
    "schema": "dbo",
    "host": "ANURAVPC",
    "port": 1433,
    "database": "AdventureWorks2025",
    "username": "sa",
    "password": "Hello@123"
})
print(f"  Status: {s}")
if s == 200:
    print(f"  Objects found: {b.get('objects')}")
    for item in b.get("items", [])[:10]:
        print(f"    - {item['name']} ({item['type']})")
    if len(b.get("items", [])) > 10:
        print(f"    ... and {len(b['items'])-10} more")
else:
    print(f"  Error: {b.get('detail', '')[:300]}")

# 6. Try discover on HumanResources schema
print("\n[6] Trying discover on SQL Server (HumanResources schema)...")
s, b = api("/discover", "POST", {
    "connection_id": sid,
    "connection_type": "source",
    "schema": "HumanResources",
    "host": "ANURAVPC",
    "port": 1433,
    "database": "AdventureWorks2025",
    "username": "sa",
    "password": "Hello@123"
})
print(f"  Status: {s}")
if s == 200:
    print(f"  Objects found: {b.get('objects')}")
    for item in b.get("items", [])[:10]:
        print(f"    - {item['name']} ({item['type']})")
else:
    print(f"  Error: {b.get('detail', '')[:300]}")

# 7. Test /validate endpoint
print("\n[7] Testing validate endpoint...")
s, b = api("/validate", "POST", {
    "job_id": str(uuid.uuid4()),
    "source_connection_id": sid,
    "target_connection_id": pid,
    "tables": [{"schema": "dbo", "table": "Department"}]
})
print(f"  Status: {s}")
if s == 200:
    print(f"  Result: {json.dumps(b, indent=2)[:500]}")
else:
    print(f"  Error: {b.get('detail', '')[:300]}")

# 8. Test /api/comparison/compare
print("\n[8] Testing comparison endpoint...")
s, b = api("/api/comparison/compare", "POST", {
    "source_connection_id": sid,
    "target_connection_id": pid,
    "source_schema": "dbo",
    "target_schema": "public"
})
print(f"  Status: {s}")
if s == 200:
    print(f"  Result: {json.dumps(b, indent=2)[:500]}")
else:
    print(f"  Error: {b.get('detail', '')[:300]}")

# Cleanup
print("\n[9] Cleaning up connections...")
api(f"/connections/{sid}", "DELETE")
api(f"/connections/{pid}", "DELETE")
print("  Done")

print("\n" + "=" * 70)
print("TESTS COMPLETE")
print("=" * 70)
