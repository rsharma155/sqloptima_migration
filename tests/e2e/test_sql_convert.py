"""
Test SQL conversion patterns individually with timeout
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
import json
import urllib.request
import urllib.error
import jwt
import sys
import concurrent.futures
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
        resp = urllib.request.urlopen(req, timeout=10)
        return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())
    except Exception as e:
        return 0, {"error": str(e)}

tests = [
    ("GETDATE()", {"sql": "SELECT GETDATE() as today", "object_type": "raw", "object_name": "t"}),
    ("TOP N", {"sql": "SELECT TOP 5 Name, Salary FROM Employees ORDER BY Salary DESC", "object_type": "raw", "object_name": "t"}),
    ("OFFSET FETCH", {"sql": "SELECT * FROM Orders ORDER BY OrderDate OFFSET 10 ROWS FETCH NEXT 20 ROWS ONLY", "object_type": "raw", "object_name": "t"}),
    ("STRING_AGG", {"sql": "SELECT STRING_AGG(Name, ', ') FROM Employees", "object_type": "raw", "object_name": "t"}),
    ("DATEADD", {"sql": "SELECT DATEADD(day, 30, OrderDate) as DueDate FROM Orders", "object_type": "raw", "object_name": "t"}),
    ("DATEDIFF", {"sql": "SELECT DATEDIFF(day, OrderDate, GETDATE()) as DaysSince FROM Orders", "object_type": "raw", "object_name": "t"}),
    ("ISNULL", {"sql": "SELECT ISNULL(FirstName, '') FROM Users", "object_type": "raw", "object_name": "t"}),
    ("CASE WHEN", {"sql": "SELECT CASE WHEN Status = 1 THEN 'Active' ELSE 'Inactive' END FROM Users", "object_type": "raw", "object_name": "t"}),
    ("Multi CTE", {"sql": "WITH cte1 AS (SELECT 1 as x), cte2 AS (SELECT 2 as y) SELECT * FROM cte1, cte2", "object_type": "raw", "object_name": "t"}),
    ("CROSS APPLY", {"sql": "SELECT * FROM (SELECT 1 as id) d CROSS APPLY (SELECT TOP 1 2 as val) emp", "object_type": "raw", "object_name": "t"}),
    ("ROW_NUMBER", {"sql": "SELECT Name, Salary, ROW_NUMBER() OVER (ORDER BY Salary DESC) as rn FROM Employees", "object_type": "raw", "object_name": "t"}),
    ("CAST", {"sql": "SELECT CAST(Price AS DECIMAL(10,2)) FROM Orders", "object_type": "raw", "object_name": "t"}),
    ("EXISTS", {"sql": "SELECT * FROM Customers c WHERE EXISTS (SELECT 1 FROM Orders o WHERE o.CustomerId = c.Id)", "object_type": "raw", "object_name": "t"}),
    ("MERGE", {"sql": "MERGE INTO Target AS T USING Source AS S ON T.Id = S.Id WHEN MATCHED THEN UPDATE SET T.Name = S.Name WHEN NOT MATCHED THEN INSERT (Id, Name) VALUES (S.Id, S.Name);", "object_type": "raw", "object_name": "t"}),
    ("OUTPUT", {"sql": "INSERT INTO Employees(Name) OUTPUT inserted.Id VALUES ('John', 50000)", "object_type": "raw", "object_name": "t"}),
    ("PIVOT", {"sql": "SELECT * FROM (SELECT Year, Amount FROM Sales) src PIVOT (SUM(Amount) FOR Year IN ([2023], [2024])) piv", "object_type": "raw", "object_name": "t"}),
    ("Procedure", {"sql": "CREATE PROCEDURE dbo.usp_test @id INT AS BEGIN SELECT @id as id END", "object_type": "procedure", "object_name": "usp_test", "schema": "dbo", "parameters": [{"name": "@id", "type": "INT"}]}),
    ("Function", {"sql": "CREATE FUNCTION dbo.ufn_test(@id INT) RETURNS INT AS BEGIN RETURN @id END", "object_type": "function", "object_name": "ufn_test", "schema": "dbo", "parameters": [{"name": "@id", "type": "INT"}]}),
    ("Trigger", {"sql": "CREATE TRIGGER trg_test ON Users AFTER INSERT AS BEGIN PRINT 'test' END", "object_type": "trigger", "object_name": "trg_test", "schema": "dbo"}),
]

print("=" * 90)
print("SQL CONVERSION TESTS")
print("=" * 90)

for name, req in tests:
    try:
        status, body = api("/convert", "POST", req)
        conv = body.get("converted_sql", "")
        issues = []
        
        if not conv:
            issues.append("Empty result")
        if body.get("errors"):
            issues.append(f"Errors: {body['errors']}")
        if body.get("success") is False:
            issues.append("success=false")
        if status != 200:
            issues.append(f"HTTP {status}")
        
        status_str = "FAIL" if issues else "PASS"
        detail = " | ".join(issues) if issues else conv[:120]
        print(f"  [{status_str}] {name:<20} -> {detail}")
        
        # Check for leftover T-SQL
        TSQL_ARTIFACTS = ["CREATE PROCEDURE", "CREATE FUNCTION", "CREATE TRIGGER"]
        if req["object_type"] == "raw":
            for artifact in TSQL_ARTIFACTS:
                if artifact.upper() in conv.upper():
                    print(f"           WARN: Contains '{artifact}' in output")
                    
    except Exception as e:
        print(f"  [FAIL] {name:<20} -> Exception: {e}")

print("=" * 90)
print("Done")
