"""Unit tests for PII column classification."""
from __future__ import annotations

from domains.discovery.pii_classifier import SensitivityClass, classify_column, sensitive_columns


def test_classify_email_column():
    result = classify_column("customer_email")
    assert result.sensitivity == SensitivityClass.PII
    assert "email" in result.reason


def test_classify_credit_card():
    result = classify_column("credit_card_number")
    assert result.sensitivity == SensitivityClass.PCI


def test_classify_non_sensitive():
    result = classify_column("order_quantity")
    assert result.sensitivity == SensitivityClass.NONE


def test_sensitive_columns_filters():
    cols = ["id", "email", "quantity", "ssn"]
    sensitive = sensitive_columns(cols)
    names = {c.column_name for c in sensitive}
    assert names == {"email", "ssn"}
