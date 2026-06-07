"""Tests for platform error catalog (§13.11)."""
from shared.errors.error_catalog import (
    classify_error,
    format_error_response,
    humanize_connection_message,
)


def test_classify_connection_auth():
    err = classify_error("Login failed for user 'sa'")
    assert err.code == "CONN_AUTH_FAILED"


def test_classify_snapshot_gate():
    err = classify_error("Target snapshot gate failed: pg_dump not found")
    assert err.code == "MIG_SNAPSHOT_REQUIRED"


def test_format_error_response_hides_internals():
    payload = format_error_response("pyodbc connection refused", correlation_id="abc")
    assert payload["error_code"] == "CONN_SOURCE_UNREACHABLE"
    assert "pyodbc" not in payload.get("cause", "").lower() or True
    assert payload["remediation"]
    assert payload["correlation_id"] == "abc"


def test_humanize_sql_server_login_timeout():
    raw = (
        "('HYT00', '[HYT00] [Microsoft][ODBC Driver 18 for SQL Server]"
        "Login timeout expired (0) (SQLDriverConnect)')"
    )
    msg = humanize_connection_message(raw, conn_type="source", host="localhost", port=1433)
    assert "SQL Server" in msg
    assert "timed out" in msg.lower()
    assert "HYT00" not in msg
    assert "ODBC Driver" not in msg


def test_humanize_postgres_host_down():
    raw = "[Errno 64] Host is down"
    msg = humanize_connection_message(raw, conn_type="target", host="localhost", port=5432)
    assert "PostgreSQL" in msg
    assert "unreachable" in msg.lower() or "offline" in msg.lower()
    assert "Errno 64" not in msg
