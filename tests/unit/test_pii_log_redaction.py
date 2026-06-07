"""Tests for PII-aware log redaction (§12.7)."""
from shared.logging.structured_logging import _redact_value, redact_sensitive_data


def test_redact_email_column_in_row():
    row = {"email": "user@example.com", "id": 1}
    redacted = _redact_value("sample_row", row)
    assert redacted["email"] == "[REDACTED_PII]"
    assert redacted["id"] == 1


def test_redact_sensitive_key_password():
    event = redact_sensitive_data(None, "info", {"password": "secret123", "event": "login"})
    assert event["password"] == "***"
