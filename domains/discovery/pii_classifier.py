"""PII / sensitive-data classification for discovered columns.
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class SensitivityClass(StrEnum):
    PII = "pii"
    PHI = "phi"
    PCI = "pci"
    CREDENTIAL = "credential"
    NONE = "none"


@dataclass(frozen=True)
class ColumnClassification:
    column_name: str
    sensitivity: SensitivityClass
    reason: str


_PII_NAME_PATTERNS: list[tuple[re.Pattern[str], SensitivityClass, str]] = [
    (re.compile(r"(?i)(ssn|social.?security|national.?id|tax.?id|passport)"), SensitivityClass.PII, "government ID"),
    (re.compile(r"(?i)(email|e_mail|mail_addr)"), SensitivityClass.PII, "email address"),
    (re.compile(r"(?i)(phone|mobile|cell|fax|telephone)"), SensitivityClass.PII, "phone number"),
    (re.compile(r"(?i)(first.?name|last.?name|full.?name|given.?name|surname)"), SensitivityClass.PII, "personal name"),
    (re.compile(r"(?i)(address|street|zip|postal|city|state|country)"), SensitivityClass.PII, "location data"),
    (re.compile(r"(?i)(dob|date.?of.?birth|birth.?date)"), SensitivityClass.PII, "date of birth"),
    (re.compile(r"(?i)(card.?number|credit.?card|pan|cvv|cvc)"), SensitivityClass.PCI, "payment card"),
    (re.compile(r"(?i)(iban|bank.?account|routing)"), SensitivityClass.PCI, "financial account"),
    (re.compile(r"(?i)(diagnosis|patient|medical|health|mrn|npi)"), SensitivityClass.PHI, "health data"),
    (re.compile(r"(?i)(password|passwd|secret|token|api.?key)"), SensitivityClass.CREDENTIAL, "credential"),
]


def classify_column(column_name: str) -> ColumnClassification:
    for pattern, sensitivity, reason in _PII_NAME_PATTERNS:
        if pattern.search(column_name):
            return ColumnClassification(column_name=column_name, sensitivity=sensitivity, reason=reason)
    return ColumnClassification(column_name=column_name, sensitivity=SensitivityClass.NONE, reason="")


def classify_columns(column_names: list[str]) -> list[ColumnClassification]:
    return [classify_column(name) for name in column_names]


def sensitive_columns(column_names: list[str]) -> list[ColumnClassification]:
    return [c for c in classify_columns(column_names) if c.sensitivity != SensitivityClass.NONE]
