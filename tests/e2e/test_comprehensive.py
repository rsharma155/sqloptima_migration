"""
Comprehensive test for the Migration Platform
Tests all API endpoints, connections, migrations, etc.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
import json
import urllib.request
import urllib.error
import uuid
import jwt
import sys
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

results = {"passed": [], "failed": [], "bugs": []}

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

def test(name, path, method="GET", data=None, expected_status=200):
    status, body = api(path, method, data)
    status_str = "PASS" if status == expected_status else "FAIL"
    if status == expected_status:
        results["passed"].append(name)
    else:
        results["failed"].append(name)
        results["bugs"].append(f"{name}: Expected {expected_status}, got {status}. Body: {body}")
    print(f"  [{status_str}] {name} -> {status}")
    if status != expected_status:
        print(f"    Error: {body}")
    return status, body

def bug(msg):
    results["bugs"].append(msg)
    print(f"  [BUG] {msg}")

print("=" * 70)
print("MIGRATION PLATFORM - COMPREHENSIVE TEST SUITE")
print("=" * 70)

# ============================================================
# 1. AUTHENTICATION
# ============================================================
print("\n" + "=" * 50)
print("1. AUTHENTICATION")
print("=" * 50)
test("Login with valid creds", "/auth/login", "POST",
     {"username": "admin", "password": "admin"}, 200)
test("Login with wrong password", "/auth/login", "POST",
     {"username": "admin", "password": "wrong"}, 401)
test("Login with empty body", "/auth/login", "POST", {}, 422)
test("Login with missing fields", "/auth/login", "POST",
     {"username": "admin"}, 422)

# ============================================================
# 2. HEALTH
# ============================================================
print("\n" + "=" * 50)
print("2. HEALTH ENDPOINT")
print("=" * 50)
status, body = test("Health check", "/health", "GET")
if status == 200:
    print(f"    Response: {body}")
    if body.get("status") != "ok":
        bug(f"Health status is '{body.get('status')}', expected 'ok'")

# ============================================================
# 3. CONNECTION MANAGEMENT
# ============================================================
print("\n" + "=" * 50)
print("3. CONNECTION MANAGEMENT")
print("=" * 50)

# Create SQL Server connection
sqlserver_conn = {
    "name": "SQL Server - AdventureWorks2025",
    "type": "source",
    "host": "ANURAVPC",
    "port": 1433,
    "database": "AdventureWorks2025",
    "username": "sa",
    "password": "Hello@123"
}
status, body = test("Create SQL Server connection", "/connections", "POST", sqlserver_conn)
sqlserver_conn_id = body.get("id") if status == 200 else None
if sqlserver_conn_id:
    print(f"    SQL Server connection ID: {sqlserver_conn_id}")

# Create PostgreSQL connection
pg_conn = {
    "name": "PostgreSQL - adventureworks2025",
    "type": "target",
    "host": "localhost",
    "port": 30432,
    "database": "adventureworks2025",
    "username": "postgres",
    "password": "Hello@123"
}
status, body = test("Create PostgreSQL connection", "/connections", "POST", pg_conn)
pg_conn_id = body.get("id") if status == 200 else None
if pg_conn_id:
    print(f"    PostgreSQL connection ID: {pg_conn_id}")

# List connections
status, body = test("List connections", "/connections", "GET")
if status == 200:
    print(f"    Found {len(body)} connections")
    for c in body:
        print(f"      - {c['name']} ({c['type']}) [{c['status']}]")

# Test SQL Server connection
status, body = test("Test SQL Server connection", f"/connections/{sqlserver_conn_id}/test", "POST")
if status == 200:
    print(f"    Result: {body.get('status')} - {body.get('message', '')}")
else:
    bug(f"SQL Server connection test failed: {body}")

# Test PostgreSQL connection
status, body = test("Test PostgreSQL connection", f"/connections/{pg_conn_id}/test", "POST")
if status == 200:
    print(f"    Result: {body.get('status')} - {body.get('message', '')}")
else:
    bug(f"PostgreSQL connection test failed: {body}")

# Update connection
upd_conn = dict(sqlserver_conn)
upd_conn["name"] = "SQL Server - Updated"
status, body = test("Update SQL Server connection", f"/connections/{sqlserver_conn_id}", "PUT", upd_conn)

# Test non-existent connection
status, body = test("Test non-existent connection", f"/connections/{uuid.uuid4()}/test", "POST", expected_status=404)

# Delete PostgreSQL connection
status, body = test("Delete PostgreSQL connection", f"/connections/{pg_conn_id}", "DELETE", expected_status=200)

# Delete non-existent connection
status, body = test("Delete non-existent connection", f"/connections/{uuid.uuid4()}", "DELETE", expected_status=404)

# ============================================================
# 4. SQL CONVERT
# ============================================================
print("\n" + "=" * 50)
print("4. SQL CONVERT")
print("=" * 50)

# Simple SELECT conversion
status, body = test("Convert simple SELECT", "/convert", "POST", {
    "sql": "SELECT TOP 10 * FROM Users WHERE CreatedDate > GETDATE() ORDER BY Id DESC",
    "object_type": "raw",
    "object_name": "test",
    "schema": "dbo"
})
if status == 200:
    print(f"    Original: SELECT TOP 10 * FROM Users WHERE CreatedDate > GETDATE() ORDER BY Id DESC")
    print(f"    Converted: {body.get('converted_sql', '')[:150]}")

# Stored procedure with parameters
status, body = test("Convert stored procedure", "/convert", "POST", {
    "sql": """
CREATE PROCEDURE dbo.usp_GetEmployees
    @DepartmentId INT,
    @IncludeInactive BIT = 0
AS
BEGIN
    SET NOCOUNT ON;
    SELECT e.EmployeeId, e.FirstName, e.LastName, e.HireDate
    FROM HumanResources.Employee e
    WHERE e.DepartmentId = @DepartmentId
        AND (@IncludeInactive = 1 OR e.IsActive = 1)
    ORDER BY e.LastName, e.FirstName;
END
""",
    "object_type": "procedure",
    "object_name": "usp_GetEmployees",
    "schema": "dbo",
    "parameters": [
        {"name": "@DepartmentId", "type": "INT"},
        {"name": "@IncludeInactive", "type": "BIT"}
    ]
})
if status == 200:
    print(f"    Success: {body.get('success')}")
    print(f"    Warnings: {body.get('warnings', [])}")
    print(f"    Converted SQL preview: {body.get('converted_sql', '')[:200]}...")

# Function with RETURN
status, body = test("Convert scalar function", "/convert", "POST", {
    "sql": """
CREATE FUNCTION dbo.ufn_GetEmployeeCount
    (@DepartmentId INT)
RETURNS INT
AS
BEGIN
    DECLARE @Count INT;
    SELECT @Count = COUNT(*) FROM HumanResources.Employee
    WHERE DepartmentId = @DepartmentId AND IsActive = 1;
    RETURN @Count;
END
""",
    "object_type": "function",
    "object_name": "ufn_GetEmployeeCount",
    "schema": "dbo",
    "parameters": [{"name": "@DepartmentId", "type": "INT"}]
})
if status == 200:
    print(f"    Success: {body.get('success')}")
    print(f"    Warnings: {body.get('warnings', [])}")

# Trigger conversion
status, body = test("Convert trigger", "/convert", "POST", {
    "sql": """
CREATE TRIGGER dbo.trg_Employee_Audit
ON HumanResources.Employee
AFTER INSERT, UPDATE, DELETE
AS
BEGIN
    SET NOCOUNT ON;
    IF EXISTS (SELECT 1 FROM inserted)
        INSERT INTO Audit.Log(TableName, Action, RecordId, ChangedBy, ChangedAt)
        SELECT 'Employee', 'INSERT', EmployeeId, SYSTEM_USER, GETDATE() FROM inserted;
END
""",
    "object_type": "trigger",
    "object_name": "trg_Employee_Audit",
    "schema": "dbo"
})
if status == 200:
    print(f"    Success: {body.get('success')}")
    print(f"    Converted SQL preview: {body.get('converted_sql', '')[:200]}...")

# Unknown object type
status, body = test("Unknown object type", "/convert", "POST", {
    "sql": "SELECT 1",
    "object_type": "unknown",
    "object_name": "test"
}, expected_status=400)

# Empty SQL
status, body = test("Empty SQL", "/convert", "POST", {
    "sql": "",
    "object_type": "raw",
    "object_name": "test"
})

# Complex T-SQL with CTEs, window functions
status, body = test("Convert complex T-SQL", "/convert", "POST", {
    "sql": """
WITH EmployeeCTE AS (
    SELECT e.EmployeeId, e.DepartmentId,
           ROW_NUMBER() OVER (PARTITION BY e.DepartmentId ORDER BY e.HireDate DESC) AS rn
    FROM HumanResources.Employee e
)
SELECT cte.EmployeeId, d.DepartmentName, d.GroupName
FROM EmployeeCTE cte
INNER JOIN HumanResources.Department d ON cte.DepartmentId = d.DepartmentId
WHERE cte.rn = 1
ORDER BY d.DepartmentName;
""",
    "object_type": "raw",
    "object_name": "test"
})
if status == 200:
    print(f"    Original has: ROW_NUMBER() OVER, CTE, JOIN")
    print(f"    Converted: {body.get('converted_sql', '')[:200]}...")

# ============================================================
# 5. MIGRATIONS
# ============================================================
print("\n" + "=" * 50)
print("5. MIGRATIONS")
print("=" * 50)

# Create a proper migration
source_id = str(uuid.uuid4())
target_id = str(uuid.uuid4())
status, body = test("Start migration", "/migrations", "POST", {
    "source_connection_id": source_id,
    "target_connection_id": target_id,
    "tables": ["Department", "Employee", "EmployeeDepartmentHistory",
               "Shift", "JobCandidate", "Address", "AddressType",
               "CountryRegion", "StateProvince", "SalesOrderHeader",
               "SalesOrderDetail", "Product", "ProductCategory",
               "ProductSubcategory", "Customer", "Person"],
    "schema": "HumanResources",
    "strategy": "chunked",
    "chunk_size": 5000,
    "parallel_workers": 4,
    "validate_after": True
})
job_id = body.get("job_id") if status == 200 else None
if job_id:
    print(f"    Job ID: {job_id}")
    print(f"    Status: {body.get('status')}")
    print(f"    Tables: {body.get('table_count')}")

# List migrations
status, body = test("List migrations", "/migrations", "GET")
if status == 200:
    print(f"    Found {len(body)} migrations")

# Get migration details
if job_id:
    status, body = test("Get migration details", f"/migrations/{job_id}", "GET")

# Migration lifecycle: pause -> resume -> stop
if job_id:
    status, body = test("Pause migration", f"/migrations/{job_id}/pause", "POST")
    if status == 200:
        # Try to pause again (should fail)
        status2, body2 = test("Pause already paused migration", f"/migrations/{job_id}/pause", "POST", expected_status=400)
        if status2 == 400:
            print(f"    Correctly rejected double-pause")

    status, body = test("Resume migration", f"/migrations/{job_id}/resume", "POST")
    if status == 200:
        # Try to resume again (should fail since it's now running)
        status2, body2 = test("Resume non-paused migration", f"/migrations/{job_id}/resume", "POST", expected_status=400)

    status, body = test("Stop migration", f"/migrations/{job_id}/stop", "POST")

# Non-existent job
status, body = test("Get non-existent migration", f"/migrations/{uuid.uuid4()}", "GET", expected_status=404)

# Migration progress (for non-existent job)
status, body = test("Progress for non-existent migration", f"/migrations/{uuid.uuid4()}/progress", "GET", expected_status=404)

# ============================================================
# 6. DISCOVER (using env variables)
# ============================================================
print("\n" + "=" * 50)
print("6. DISCOVER ENDPOINT")
print("=" * 50)
conn_id = str(uuid.uuid4())
status, body = test("Discover SQL Server schema", "/discover", "POST", {
    "connection_id": conn_id,
    "connection_type": "source",
    "schema": "dbo"
}, expected_status=200)
if status == 200:
    print(f"    Objects found: {body.get('objects', 0)}")
    items = body.get('items', [])
    if items:
        types = {}
        for item in items:
            t = item.get('type', 'unknown')
            types[t] = types.get(t, 0) + 1
        print(f"    Object types: {types}")
        for item in items[:5]:
            print(f"      - {item['name']} ({item['type']})")
        if len(items) > 5:
            print(f"      ... and {len(items)-5} more")
    else:
        bug("Discover returned 0 objects")
else:
    bug(f"Discover endpoint failed: {body}")

# Discover with invalid connection_type
status, body = test("Discover with invalid type", "/discover", "POST", {
    "connection_id": str(uuid.uuid4()),
    "connection_type": "invalid",
}, expected_status=502)

# ============================================================
# 7. VALIDATION
# ============================================================
print("\n" + "=" * 50)
print("7. VALIDATION ENDPOINT")
print("=" * 50)
status, body = test("Validate migration", "/validate", "POST", {
    "job_id": job_id or str(uuid.uuid4()),
    "source_connection_id": source_id,
    "target_connection_id": target_id,
    "tables": [{"schema": "dbo", "table": "Department"},
               {"schema": "HumanResources", "table": "Employee"}]
})
if status == 200:
    print(f"    Validation report: {body}")
else:
    print(f"    Expected failure (needs DB connections): {body.get('detail', '')[:150]}")

# ============================================================
# 8. COMPARISON
# ============================================================
print("\n" + "=" * 50)
print("8. SCHEMA COMPARISON")
print("=" * 50)
status, body = test("Compare databases", "/api/comparison/compare", "POST", {
    "source_connection_id": source_id,
    "target_connection_id": target_id,
    "source_schema": "dbo",
    "target_schema": "public"
})
if status == 200:
    print(f"    Comparison result: {body}")
else:
    print(f"    Expected failure (needs discovery): {body.get('detail', '')[:150]}")

# ============================================================
# 9. AUTH PROTECTION
# ============================================================
print("\n" + "=" * 50)
print("9. AUTH PROTECTION - Unauthenticated requests")
print("=" * 50)

def api_no_auth(path, method="GET", data=None):
    url = f"{BASE}{path}"
    body = json.dumps(data).encode() if data else None
    headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())
    except Exception as e:
        return 0, {"error": str(e)}

status, body = api_no_auth("/connections")
if status == 401:
    results["passed"].append("Unauthenticated /connections rejected")
    print(f"  [PASS] /connections without auth -> {status} (correctly rejected)")
else:
    results["failed"].append("Unauthenticated /connections")
    bug(f"/connections without auth returned {status}, expected 401")

status, body = api_no_auth("/migrations", "POST", {
    "source_connection_id": str(uuid.uuid4()),
    "target_connection_id": str(uuid.uuid4()),
    "tables": ["test"]
})
if status == 401:
    results["passed"].append("Unauthenticated /migrations POST rejected")
    print(f"  [PASS] /migrations POST without auth -> {status} (correctly rejected)")
else:
    bug(f"/migrations POST without auth returned {status}, expected 401")

# Health should be public
status, body = api_no_auth("/health")
if status == 200:
    results["passed"].append("Health endpoint is public")
    print(f"  [PASS] /health without auth -> {status} (public endpoint)")
else:
    bug(f"/health without auth returned {status}, expected 200")

# ============================================================
# SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("TEST SUMMARY")
print("=" * 70)
print(f"  Passed: {len(results['passed'])}")
print(f"  Failed: {len(results['failed'])}")
print(f"  Total:  {len(results['passed']) + len(results['failed'])}")

if results["bugs"]:
    print(f"\n  BUGS / ISSUES FOUND ({len(results['bugs'])}):")
    for i, b in enumerate(results["bugs"], 1):
        print(f"    {i}. {b}")

if results["bugs"]:
    sys.exit(1)
else:
    sys.exit(0)
