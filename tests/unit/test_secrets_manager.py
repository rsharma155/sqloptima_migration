"""
Module: test_secrets_manager.py
Purpose: Unit tests for secrets management / encryption
Author: Migration Platform Team
Created: 2026-05-22
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

import pytest

from shared.security.secrets_manager import SecretsManager


_KEY_A = "test-key-alpha-not-for-production-use-01"
_KEY_B = "test-key-beta-not-for-production-use-002"


class TestSecretsManager:
    def test_encrypt_decrypt_roundtrip(self):
        mgr = SecretsManager(master_key=_KEY_A)
        plaintext = "Server=localhost;Database=mydb;UID=sa;PWD=MyP@ss!"
        encrypted = mgr.encrypt(plaintext)
        decrypted = mgr.decrypt(encrypted)
        assert decrypted == plaintext
        assert encrypted != plaintext

    def test_same_plaintext_different_ciphertext_each_time(self):
        # Random salt per operation means two encryptions of the same value differ.
        mgr = SecretsManager(master_key=_KEY_A)
        plaintext = "password123"
        e1 = mgr.encrypt(plaintext)
        e2 = mgr.encrypt(plaintext)
        assert e1 != e2

    def test_requires_master_key(self):
        import os
        env_backup = os.environ.pop("MIGRATION_MASTER_KEY", None)
        try:
            with pytest.raises(ValueError):
                SecretsManager()
        finally:
            if env_backup is not None:
                os.environ["MIGRATION_MASTER_KEY"] = env_backup

    def test_decrypt_with_wrong_key_fails(self):
        mgr1 = SecretsManager(master_key=_KEY_A)
        mgr2 = SecretsManager(master_key=_KEY_B)
        encrypted = mgr1.encrypt("secret")
        with pytest.raises(Exception):
            mgr2.decrypt(encrypted)


class TestMasterKeyStrength:
    """Master key must meet a minimum length floor (Issue #8)."""

    def test_rejects_short_master_key(self):
        with pytest.raises(ValueError, match="at least"):
            SecretsManager(master_key="too-short")

    def test_rejects_empty_after_strip(self):
        with pytest.raises(ValueError):
            SecretsManager(master_key="   ")

    def test_accepts_key_at_minimum_length(self):
        from shared.security.secrets_manager import MIN_MASTER_KEY_LENGTH

        key = "k" * MIN_MASTER_KEY_LENGTH
        mgr = SecretsManager(master_key=key)
        assert mgr.decrypt(mgr.encrypt("ok")) == "ok"

    def test_error_message_is_actionable(self):
        """The error should tell the operator how to generate a strong key."""
        with pytest.raises(ValueError) as exc:
            SecretsManager(master_key="short")
        assert "token_urlsafe" in str(exc.value)
