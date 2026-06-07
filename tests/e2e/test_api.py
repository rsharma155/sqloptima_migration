"""Test all API endpoints thoroughly
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

def make_token():
    payload = {
        "sub": "testuser",
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(hours=24),
    }
    return jwt.encode(payload, SECRET, algorithm="HS256")

TOKEN = make_token()
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
}

def api(path, method="GET", data=None):
    url = f"{BASE}{path}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=HEADERS, method=method)
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())
    except Exception as e:
        return 0, {"error": str(e)}

def test_endpoint(name, path, method="GET", data=None):
    status, body = api(path, method, data)
    status_str = "PASS" if status < 400 else "FAIL"
    print(f"  [{status_str}] {name} -> {status}")
    if status >= 400:
        print(f"    Error: {body}")
    return status, body

print("=" * 60)
print("API ENDPOINT TESTS")
print("=" * 60)

# 1. Health (public, no auth needed)
print("\n1. HEALTH ENDPOINT")
test_endpoint("GET /health", "/health")

# 2. Convert SQL
print("\n2. SQL CONVERT ENDPOINT")

# Test basic procedure conversion
status, body = test_endpoint("Simple procedure", "/convert", "POST", {
    "sql": "CREATE PROCEDURE dbo.usp_test AS BEGIN SELECT * FROM Users; END",
    "object_type": "procedure",
    "object_name": "usp_test",
    "schema": "dbo"
})
if status == 200:
    print(f"    Converted SQL: {body.get('converted_sql', '')[:150]}...")
    print(f"    Success: {body.get('success')}")

# Test function conversion
status, body = test_endpoint("Simple function", "/convert", "POST", {
    "sql": "CREATE FUNCTION dbo.ufn_Test(@id INT) RETURNS INT AS BEGIN RETURN @id; END",
    "object_type": "function",
    "object_name": "ufn_Test",
    "schema": "dbo",
    "parameters": [{"name": "@id", "type": "INT"}]
})
if status == 200:
    print(f"    Converted: {body.get('converted_sql', '')[:150]}...")

# Test trigger conversion
status, body = test_endpoint("Simple trigger", "/convert", "POST", {
    "sql": "CREATE TRIGGER trg_test ON Users AFTER INSERT AS BEGIN PRINT 'trigger'; END",
    "object_type": "trigger",
    "object_name": "trg_test",
    "schema": "dbo"
})
if status == 200:
    print(f"    Converted: {body.get('converted_sql', '')[:150]}...")

# Test invalid object type
status, body = test_endpoint("Invalid object type", "/convert", "POST", {
    "sql": "SELECT 1",
    "object_type": "unknown_type",
    "object_name": "test",
})
if status >= 400:
    print(f"    Correctly rejected: {body}")

# 3. Migration endpoints
print("\n3. MIGRATION ENDPOINTS")

# Start a migration
job_uuid = str(uuid.uuid4())
source_id = str(uuid.uuid4())
target_id = str(uuid.uuid4())
status, body = test_endpoint("POST /migrations", "/migrations", "POST", {
    "source_connection_id": source_id,
    "target_connection_id": target_id,
    "tables": ["Department", "Employee"],
    "schema": "HumanResources",
    "strategy": "chunked",
    "chunk_size": 5000,
    "parallel_workers": 2,
    "validate_after": True
})
job_id = None
if status == 200:
    job_id = body.get("job_id")
    print(f"    Job ID: {job_id}")
    print(f"    Status: {body.get('status')}")

# Get migration details
if job_id:
    test_endpoint(f"GET /migrations/{job_id}", f"/migrations/{job_id}")

    # Pause
    test_endpoint(f"POST /migrations/{job_id}/pause", f"/migrations/{job_id}/pause", "POST")

    # Pause again (should fail - already paused)
    status, body = test_endpoint(f"POST /migrations/{job_id}/pause (again)", f"/migrations/{job_id}/pause", "POST")
    if status >= 400:
        print(f"    Correctly rejected double-pause: {body.get('detail', '')}")

    # Resume
    test_endpoint(f"POST /migrations/{job_id}/resume", f"/migrations/{job_id}/resume", "POST")

    # Stop
    test_endpoint(f"POST /migrations/{job_id}/stop", f"/migrations/{job_id}/stop", "POST")

    # Stop again (should work - no running check)
    test_endpoint(f"POST /migrations/{job_id}/stop (again)", f"/migrations/{job_id}/stop", "POST")

    # Progress
    test_endpoint(f"GET /migrations/{job_id}/progress", f"/migrations/{job_id}/progress")

    # Table progress
    test_endpoint(f"GET /migrations/{job_id}/tables/Department/progress", f"/migrations/{job_id}/tables/Department/progress")

# Non-existent job
test_endpoint("GET non-existent job", f"/migrations/{uuid.uuid4()}")

# 4. Discover endpoint
print("\n4. DISCOVER ENDPOINT (will likely fail - DiscoveryEngine missing constructor arg)")
status, body = test_endpoint("POST /discover", f"/discover?connection_id={source_id}&schema=dbo", "POST")
# This is expected to fail due to code bug (described in notes)

# 5. Validate endpoint
print("\n5. VALIDATE ENDPOINT (will try but may fail without connections)")
status, body = test_endpoint("POST /validate", "/validate", "POST", {
    "job_id": job_id or str(uuid.uuid4()),
    "source_connection_id": source_id,
    "target_connection_id": target_id,
    "tables": [{"schema": "dbo", "table": "test"}]
})
if status >= 400:
    print(f"    Expected (needs working connections): {body.get('detail', '')[:100]}")

# 6. Comparison endpoint
print("\n6. COMPARISON ENDPOINT")
status, body = test_endpoint("POST /api/comparison/compare", "/api/comparison/compare", "POST", {
    "source_connection_id": source_id,
    "target_connection_id": target_id,
    "source_schema": "dbo",
    "target_schema": "public"
})
if status >= 400:
    print(f"    Expected (needs working discovery): {body.get('detail', '')[:100]}")

print("\n" + "=" * 60)
print("API TESTING COMPLETE")
print("=" * 60)
