# Author: Ravi Sharma
# Copyright (c) 2026 Ravi Sharma
# SPDX-License-Identifier: MIT

"""Shared FastAPI dependencies and process-wide singletons.

Centralising these here breaks the circular-import risk that would arise if
routers imported from main.py.
"""

from __future__ import annotations

from shared.security.secret_provider import SecretProvider, build_secret_provider
from shared.security.secrets_manager import SecretsManager

_secrets: SecretsManager | None = None
_secret_provider: SecretProvider | None = None


def set_secrets(sm: SecretsManager) -> None:
    global _secrets
    _secrets = sm


def get_secrets() -> SecretsManager:
    global _secrets
    if _secrets is None:
        _secrets = SecretsManager()  # raises ValueError if MIGRATION_MASTER_KEY absent
    return _secrets


def set_secret_provider(sp: SecretProvider) -> None:
    global _secret_provider
    _secret_provider = sp


def get_secret_provider() -> SecretProvider:
    global _secret_provider
    if _secret_provider is None:
        _secret_provider = build_secret_provider()
    return _secret_provider
