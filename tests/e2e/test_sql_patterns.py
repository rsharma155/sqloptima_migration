"""
Test SQL conversion patterns comprehensively
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""
import json
import urllib.request
import urllib.error
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
        resp = urllib.request.urlopen(req, timeout=15)
        return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())
    except Exception as e:
        return 0, {"error": str(e)}

tests = [
    ("GETDATE()", {"sql": "SELECT GETDATE() as today", "object_type": "raw", "object_name": "t"}),
    ("TOP N", {"sql": "SELECT TOP 5 Name, Salary FROM Employees ORDER BY Salary DESC", "object_type": "raw", "object_name": "t"}),
    ("WITH TIES", {"sql": "SELECT TOP 10 WITH TIES Name, Score FROM Results ORDER BY Score DESC", "object_type": "raw", "object_name": "t"}),
    ("OFFSET FETCH", {"sql": "SELECT * FROM Orders ORDER BY OrderDate OFFSET 10 ROWS FETCH NEXT 20 ROWS ONLY", "object_type": "raw", "object_name": "t"}),
    ("STRING_AGG", {"sql": "SELECT STRING_AGG(Name, ', ') FROM Employees", "object_type": "raw", "object_name": "t"}),
    ("DATEPART", {"sql": "SELECT DATEPART(year, OrderDate) as Year, COUNT(*) FROM Orders GROUP BY DATEPART(year, OrderDate)", "object_type": "raw", "object_name": "t"}),
    ("DATEADD", {"sql": "SELECT DATEADD(day, 30, OrderDate) as DueDate FROM Orders", "object_type": "raw", "object_name": "t"}),
    ("DATEDIFF", {"sql": "SELECT DATEDIFF(day, OrderDate, GETDATE()) as DaysSince FROM Orders", "object_type": "raw", "object_name": "t"}),
    ("ISNULL", {"sql": "SELECT ISNULL(FirstName, '') + ' ' + ISNULL(LastName, '') as FullName FROM Users", "object_type": "raw", "object_name": "t"}),
    ("CAST STUFF", {"sql": "SELECT CAST(Price AS DECIMAL(10,2)), CONVERT(VARCHAR(10), OrderDate, 101) FROM Orders", "object_type": "raw", "object_name": "t"}),
    ("CASE WHEN", {"sql": "SELECT CASE WHEN Status = 1 THEN 'Active' WHEN Status = 0 THEN 'Inactive' ELSE 'Unknown' END as StatusText FROM Users", "object_type": "raw", "object_name": "t"}),
    ("Multi CTE", {"sql": "WITH SalesCTE AS (SELECT SalesPersonID, SUM(TotalDue) as TotalSales FROM SalesOrderHeader GROUP BY SalesPersonID), RankedCTE AS (SELECT *, RANK() OVER (ORDER BY TotalSales DESC) as rnk FROM SalesCTE) SELECT * FROM RankedCTE WHERE rnk <= 5", "object_type": "raw", "object_name": "t"}),
    ("PIVOT", {"sql": "SELECT * FROM (SELECT Year, Quarter, Amount FROM Sales) src PIVOT (SUM(Amount) FOR Quarter IN ([Q1], [Q2], [Q3], [Q4])) piv", "object_type": "raw", "object_name": "t"}),
    ("MERGE", {"sql": "MERGE INTO Target AS T USING Source AS S ON T.Id = S.Id WHEN MATCHED THEN UPDATE SET T.Name = S.Name WHEN NOT MATCHED THEN INSERT (Id, Name) VALUES (S.Id, S.Name);", "object_type": "raw", "object_name": "t"}),
    ("TRY CATCH", {"sql": "BEGIN TRY SELECT 1/0; END TRY BEGIN CATCH SELECT ERROR_MESSAGE() as Error; END CATCH", "object_type": "raw", "object_name": "t"}),
    ("OUTPUT", {"sql": "INSERT INTO Employees(Name, Salary) OUTPUT inserted.Id VALUES ('John', 50000)", "object_type": "raw", "object_name": "t"}),
    ("CROSS APPLY", {"sql": "SELECT * FROM Departments d CROSS APPLY (SELECT TOP 3 * FROM Employees e WHERE e.DepartmentId = d.Id ORDER BY e.HireDate DESC) emp", "object_type": "raw", "object_name": "t"}),
    ("OUTER APPLY", {"sql": "SELECT * FROM Customers c OUTER APPLY (SELECT TOP 1 * FROM Orders o WHERE o.CustomerId = c.Id ORDER BY o.OrderDate DESC) last", "object_type": "raw", "object_name": "t"}),
    ("NULLIF", {"sql": "SELECT NULLIF(Price, 0) FROM Products", "object_type": "raw", "object_name": "t"}),
    ("COALESCE", {"sql": "SELECT COALESCE(Phone, MobilePhone, Email, 'N/A') FROM Contacts", "object_type": "raw", "object_name": "t"}),
    ("EXISTS", {"sql": "SELECT * FROM Customers c WHERE EXISTS (SELECT 1 FROM Orders o WHERE o.CustomerId = c.Id AND o.Total > 1000)", "object_type": "raw", "object_name": "t"}),
    ("FOR XML PATH", {"sql": "SELECT STUFF((SELECT ', ' + Name FROM Cities FOR XML PATH('')), 1, 2, '') as CityList", "object_type": "raw", "object_name": "t"}),
    ("BULK INSERT", {"sql": "BULK INSERT dbo.Employees FROM 'data.csv' WITH (FIELDTERMINATOR = ',', ROWTERMINATOR = '\\n')", "object_type": "raw", "object_name": "t"}),

]

print("=" * 90)
print("SQL CONVERSION PATTERN TESTS")
print("=" * 90)
print(f"{'Test Name':<25} {'Status':<8} {'Details/Converted Preview'}")
print("-" * 90)

passed = 0
failed = 0
issues_list = []

for name, req in tests:
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
    
    if issues:
        status_str = "FAIL"
        failed += 1
        issues_list.append(f"  [{name}] {' | '.join(issues)}")
    else:
        status_str = "PASS"
        passed += 1
    
    detail = " | ".join(issues) if issues else conv[:100]
    print(f"{name:<25} {status_str:<8} {detail}")

print("-" * 90)
print(f"Passed: {passed}, Failed: {failed}")

# Check for leftover T-SQL in raw conversions
print("\n=== QUALITY CHECK: Leftover T-SQL in raw conversions ===")
tsql_artifacts = ["CREATE PROCEDURE", "CREATE FUNCTION", "CREATE TRIGGER",
                   "AS BEGIN", "SET NOCOUNT", "DECLARE @"]
for name, req in tests:
    status, body = api("/convert", "POST", req)
    conv = body.get("converted_sql", "")
    for artifact in tsql_artifacts:
        if artifact.upper() in conv.upper():
            print(f"  [ISSUE] {name}: Contains '{artifact}' in output")
            break

# Check for invalid PG syntax  
print("\n=== QUALITY CHECK: Invalid PG syntax patterns ===")
pg_issues = ["CREATE OR REPLACE CREATE", "DECLARE\nBEGIN\nCREATE PROCEDURE",
             "$function$\n$function$"]
for name, req in tests:
    status, body = api("/convert", "POST", req)
    conv = body.get("converted_sql", "")
    for issue in pg_issues:
        if issue.upper() in conv.upper():
            print(f"  [ISSUE] {name}: Contains '{issue}' pattern")
            break
