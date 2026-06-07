# Author: Ravi Sharma
# Copyright (c) 2026 Ravi Sharma
# SPDX-License-Identifier: MIT

"""TDD tests for SecretsManager key rotation (L-14).

Contract:
  encrypt_v2:
  - Produces ciphertext with prefix "v2:<key_id>:<salt_b64>:<fernet_token>".
  - Default key_id is "current".
  - Decryptable with decrypt_auto() using the same master key.

  decrypt_auto:
  - Handles legacy format (no version prefix): "base64(salt):fernet_token".
  - Handles v1: prefix format (future-proof alias).
  - Handles v2:<key_id>: prefix format.
  - Raises ValueError on unrecognised / corrupt formats.
  - Existing decrypt() method also handles all formats (backward-compat).

  rotate:
  - Takes a list of ciphertexts (any format) encrypted with self._master_key.
  - Returns re-encrypted ciphertexts using new_master_key in v2 format.
  - Decrypting any result with new_master_key yields the original plaintext.
  - Does NOT mutate the SecretsManager instance.
  - Raises ValueError if any ciphertext cannot be decrypted (preserves atomicity
    semantics — caller decides whether to commit partial results).

  Round-trip invariants:
  - encrypt(p) → decrypt(c) == p          [legacy encrypt + legacy decrypt]
  - encrypt_v2(p) → decrypt_auto(c) == p  [v2 encrypt + auto decrypt]
  - encrypt(p) → decrypt_auto(c) == p     [legacy encrypt + auto decrypt]
"""

from __future__ import annotations

import pytest

from shared.security.secrets_manager import SecretsManager

OLD_KEY = "old-master-key-at-least-32-characters-long!!"
NEW_KEY = "new-master-key-at-least-32-characters-long!!"


# ═══════════════════════════════════════════════════════════════════════════
# encrypt_v2
# ═══════════════════════════════════════════════════════════════════════════

class TestEncryptV2:
    def test_output_has_v2_prefix(self):
        sm = SecretsManager(master_key=OLD_KEY)
        ct = sm.encrypt_v2("secret")
        assert ct.startswith("v2:"), f"Expected v2: prefix, got {ct[:10]!r}"

    def test_default_key_id_is_current(self):
        sm = SecretsManager(master_key=OLD_KEY)
        ct = sm.encrypt_v2("secret")
        parts = ct.split(":", 3)
        assert parts[1] == "current"

    def test_custom_key_id_is_embedded(self):
        sm = SecretsManager(master_key=OLD_KEY)
        ct = sm.encrypt_v2("secret", key_id="v20260601")
        parts = ct.split(":", 3)
        assert parts[1] == "v20260601"

    def test_has_four_colon_separated_parts(self):
        sm = SecretsManager(master_key=OLD_KEY)
        ct = sm.encrypt_v2("secret")
        parts = ct.split(":", 3)
        assert len(parts) == 4, f"Expected 4 parts, got {parts}"

    def test_two_encryptions_differ(self):
        sm = SecretsManager(master_key=OLD_KEY)
        assert sm.encrypt_v2("same") != sm.encrypt_v2("same")  # random salt

    def test_roundtrip_via_decrypt_auto(self):
        sm = SecretsManager(master_key=OLD_KEY)
        plaintext = "my-database-password"
        ct = sm.encrypt_v2(plaintext)
        assert sm.decrypt_auto(ct) == plaintext

    def test_roundtrip_via_legacy_decrypt(self):
        sm = SecretsManager(master_key=OLD_KEY)
        ct = sm.encrypt_v2("secret")
        assert sm.decrypt(ct) == "secret"


# ═══════════════════════════════════════════════════════════════════════════
# decrypt_auto
# ═══════════════════════════════════════════════════════════════════════════

class TestDecryptAuto:
    def test_decrypts_legacy_format(self):
        sm = SecretsManager(master_key=OLD_KEY)
        legacy_ct = sm.encrypt("legacy-secret")
        # encrypt() produces the old format — decrypt_auto must handle it
        assert sm.decrypt_auto(legacy_ct) == "legacy-secret"

    def test_decrypts_v2_format(self):
        sm = SecretsManager(master_key=OLD_KEY)
        v2_ct = sm.encrypt_v2("v2-secret")
        assert sm.decrypt_auto(v2_ct) == "v2-secret"

    def test_raises_on_empty_string(self):
        sm = SecretsManager(master_key=OLD_KEY)
        with pytest.raises(ValueError):
            sm.decrypt_auto("")

    def test_raises_on_garbage(self):
        sm = SecretsManager(master_key=OLD_KEY)
        with pytest.raises((ValueError, Exception)):
            sm.decrypt_auto("this-is-not-a-valid-ciphertext")

    def test_raises_when_wrong_key_used(self):
        sm_old = SecretsManager(master_key=OLD_KEY)
        sm_new = SecretsManager(master_key=NEW_KEY)
        ct = sm_old.encrypt_v2("secret")
        with pytest.raises((ValueError, Exception)):
            sm_new.decrypt_auto(ct)

    def test_legacy_decrypt_also_handles_v2(self):
        """The existing decrypt() must remain backward-compatible with v2 format."""
        sm = SecretsManager(master_key=OLD_KEY)
        v2_ct = sm.encrypt_v2("hello")
        assert sm.decrypt(v2_ct) == "hello"


# ═══════════════════════════════════════════════════════════════════════════
# rotate
# ═══════════════════════════════════════════════════════════════════════════

class TestRotate:
    def test_rotate_produces_same_number_of_ciphertexts(self):
        sm = SecretsManager(master_key=OLD_KEY)
        originals = [sm.encrypt(f"secret-{i}") for i in range(5)]
        rotated = sm.rotate(originals, new_master_key=NEW_KEY)
        assert len(rotated) == 5

    def test_rotated_ciphertexts_decrypt_with_new_key(self):
        sm_old = SecretsManager(master_key=OLD_KEY)
        sm_new = SecretsManager(master_key=NEW_KEY)

        plaintexts = ["password1", "password2", "password3"]
        originals = [sm_old.encrypt(p) for p in plaintexts]
        rotated = sm_old.rotate(originals, new_master_key=NEW_KEY)

        for rot, expected in zip(rotated, plaintexts):
            assert sm_new.decrypt_auto(rot) == expected

    def test_rotated_ciphertexts_use_v2_format(self):
        sm = SecretsManager(master_key=OLD_KEY)
        originals = [sm.encrypt("pw")]
        rotated = sm.rotate(originals, new_master_key=NEW_KEY)
        assert rotated[0].startswith("v2:")

    def test_rotate_handles_mixed_formats(self):
        sm_old = SecretsManager(master_key=OLD_KEY)
        sm_new = SecretsManager(master_key=NEW_KEY)

        legacy = sm_old.encrypt("from-legacy")
        v2 = sm_old.encrypt_v2("from-v2")

        rotated = sm_old.rotate([legacy, v2], new_master_key=NEW_KEY)
        assert sm_new.decrypt_auto(rotated[0]) == "from-legacy"
        assert sm_new.decrypt_auto(rotated[1]) == "from-v2"

    def test_rotate_does_not_mutate_self(self):
        sm = SecretsManager(master_key=OLD_KEY)
        original_key = sm.master_key
        sm.rotate([sm.encrypt("pw")], new_master_key=NEW_KEY)
        assert sm.master_key == original_key

    def test_rotate_empty_list_returns_empty_list(self):
        sm = SecretsManager(master_key=OLD_KEY)
        assert sm.rotate([], new_master_key=NEW_KEY) == []

    def test_rotate_with_bad_ciphertext_raises(self):
        sm = SecretsManager(master_key=OLD_KEY)
        with pytest.raises((ValueError, Exception)):
            sm.rotate(["not-a-valid-ciphertext"], new_master_key=NEW_KEY)

    def test_rotate_v2_to_v2(self):
        """Rotating already-v2 ciphertexts works (key upgrade scenario)."""
        sm_v1 = SecretsManager(master_key=OLD_KEY)
        sm_v2 = SecretsManager(master_key=NEW_KEY)

        ct_v2 = sm_v1.encrypt_v2("sensitive")
        rotated = sm_v1.rotate([ct_v2], new_master_key=NEW_KEY)
        assert sm_v2.decrypt_auto(rotated[0]) == "sensitive"


# ═══════════════════════════════════════════════════════════════════════════
# Existing tests must still pass (backward compatibility)
# ═══════════════════════════════════════════════════════════════════════════

class TestBackwardCompatibility:
    def test_legacy_encrypt_decrypt_roundtrip(self):
        sm = SecretsManager(master_key=OLD_KEY)
        ct = sm.encrypt("my-password")
        assert sm.decrypt(ct) == "my-password"

    def test_legacy_ciphertext_format_unchanged(self):
        """The legacy encrypt() format must stay as base64(salt):fernet_token."""
        sm = SecretsManager(master_key=OLD_KEY)
        ct = sm.encrypt("test")
        # Legacy: two colon-separated parts, no version prefix
        assert not ct.startswith("v"), "Legacy encrypt() must not add version prefix"
        parts = ct.split(":", 1)
        assert len(parts) == 2
