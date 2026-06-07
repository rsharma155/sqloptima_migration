"""
Module: secrets_manager.py
Purpose: Encryption and secrets management for database credentials
Author: Migration Platform Team
Created: 2026-05-22
Domain: Shared Security
Author: Ravi Sharma
Copyright (c) 2026 Ravi Sharma
SPDX-License-Identifier: MIT
"""

import base64
import os
import secrets

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


SALT_LENGTH = 16
PBKDF2_ITERATIONS = 600000

# Minimum master-key length. A 32-char floor matches the recommended
# ``secrets.token_urlsafe(32)`` generator and rejects weak/typo'd keys before
# they are ever used to derive an encryption key (Issue #8).
MIN_MASTER_KEY_LENGTH = 32


class SecretsManager:
    """Manages encryption/decryption of sensitive configuration values.

    Uses Fernet symmetric encryption with a key derived from a master key
    using PBKDF2 with a random salt per encryption operation.

    The master key MUST be provided explicitly or via the
    MIGRATION_MASTER_KEY environment variable. No fallback key is generated.
    """

    def __init__(self, master_key: str | None = None):
        self._master_key = master_key or os.environ.get("MIGRATION_MASTER_KEY")
        if not self._master_key or not self._master_key.strip():
            raise ValueError(
                "A master key is required. Set MIGRATION_MASTER_KEY "
                "environment variable or pass master_key to SecretsManager."
            )
        if len(self._master_key) < MIN_MASTER_KEY_LENGTH:
            raise ValueError(
                f"Master key must be at least {MIN_MASTER_KEY_LENGTH} characters "
                f"(got {len(self._master_key)}). Generate a strong key with: "
                'python -c "import secrets; print(secrets.token_urlsafe(32))"'
            )

    @staticmethod
    def _generate_salt() -> bytes:
        """Generate a cryptographically random salt."""
        return secrets.token_bytes(SALT_LENGTH)

    @staticmethod
    def _derive_key(master_key: str, salt: bytes) -> bytes:
        """Derive a Fernet-compatible key from the master key and salt."""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=PBKDF2_ITERATIONS,
        )
        key = base64.urlsafe_b64encode(kdf.derive(master_key.encode()))
        return key

    # ------------------------------------------------------------------
    # Encryption
    # ------------------------------------------------------------------

    def encrypt(self, plaintext: str) -> str:
        """Encrypt using the legacy format for backward compatibility.

        Format: ``base64(salt):fernet_token``

        New code should prefer :meth:`encrypt_v2` which carries a version
        prefix and key-id for future rotation support.
        """
        salt = self._generate_salt()
        fernet = Fernet(self._derive_key(self._master_key, salt))
        token = fernet.encrypt(plaintext.encode()).decode()
        salt_b64 = base64.urlsafe_b64encode(salt).decode()
        return f"{salt_b64}:{token}"

    def encrypt_v2(self, plaintext: str, key_id: str = "current") -> str:
        """Encrypt using the versioned v2 format.

        Format: ``v2:<key_id>:<base64(salt)>:<fernet_token>``

        The ``key_id`` is an opaque label that identifies which master-key
        version encrypted the data — useful when tracking which credentials
        need re-encryption after a key rotation.

        Args:
            plaintext: The secret value to encrypt.
            key_id:    Human-readable label for the key version (default: ``"current"``).

        Returns:
            A ``v2:`` prefixed ciphertext string.
        """
        salt = self._generate_salt()
        fernet = Fernet(self._derive_key(self._master_key, salt))
        token = fernet.encrypt(plaintext.encode()).decode()
        salt_b64 = base64.urlsafe_b64encode(salt).decode()
        return f"v2:{key_id}:{salt_b64}:{token}"

    # ------------------------------------------------------------------
    # Decryption
    # ------------------------------------------------------------------

    def _decrypt_legacy(self, ciphertext: str) -> str:
        """Decrypt a legacy (no-prefix) ciphertext: ``base64(salt):fernet_token``."""
        try:
            salt_b64, token = ciphertext.split(":", 1)
            salt = base64.urlsafe_b64decode(salt_b64)
            fernet = Fernet(self._derive_key(self._master_key, salt))
            return fernet.decrypt(token.encode()).decode()
        except (ValueError, base64.binascii.Error) as exc:
            raise ValueError("Invalid legacy ciphertext format") from exc

    def _decrypt_v2(self, ciphertext: str) -> str:
        """Decrypt a v2-prefixed ciphertext: ``v2:<key_id>:<base64(salt)>:<fernet_token>``."""
        try:
            # Strip the "v2:" prefix and split remaining into 3 parts
            rest = ciphertext[3:]  # remove "v2:"
            _key_id, salt_b64, token = rest.split(":", 2)
            salt = base64.urlsafe_b64decode(salt_b64)
            fernet = Fernet(self._derive_key(self._master_key, salt))
            return fernet.decrypt(token.encode()).decode()
        except (ValueError, base64.binascii.Error) as exc:
            raise ValueError("Invalid v2 ciphertext format") from exc

    def decrypt_auto(self, ciphertext: str) -> str:
        """Decrypt a ciphertext of any supported format.

        Dispatches based on version prefix:
        - ``v2:…``        → v2 format (key_id embedded)
        - ``v1:…``        → v1 format (same wire as legacy, explicit prefix)
        - anything else   → legacy format (``base64(salt):fernet_token``)

        Args:
            ciphertext: The ciphertext produced by :meth:`encrypt` or :meth:`encrypt_v2`.

        Returns:
            The original plaintext string.

        Raises:
            ValueError: If the ciphertext is empty, malformed, or was encrypted
                        with a different master key.
        """
        if not ciphertext:
            raise ValueError("Cannot decrypt empty ciphertext")
        if ciphertext.startswith("v2:"):
            return self._decrypt_v2(ciphertext)
        # v1: prefix is treated identically to legacy (no key_id in wire format)
        if ciphertext.startswith("v1:"):
            return self._decrypt_legacy(ciphertext[3:])
        return self._decrypt_legacy(ciphertext)

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt a ciphertext — handles all formats (backward compatible).

        Delegates to :meth:`decrypt_auto` so callers that already use
        ``decrypt()`` automatically gain support for v2 ciphertexts.
        """
        return self.decrypt_auto(ciphertext)

    # ------------------------------------------------------------------
    # Key rotation
    # ------------------------------------------------------------------

    def rotate(self, ciphertexts: list[str], new_master_key: str, new_key_id: str = "current") -> list[str]:
        """Re-encrypt *ciphertexts* from the current master key to *new_master_key*.

        Each ciphertext may be in any supported format (legacy, v2).  The
        returned ciphertexts are all in v2 format so they carry the version
        label for the next rotation cycle.

        This method does NOT mutate ``self``; the caller is responsible for
        persisting the rotated ciphertexts and then switching to a
        ``SecretsManager`` initialised with *new_master_key*.

        Args:
            ciphertexts:    Encrypted values produced by this instance's master key.
            new_master_key: The replacement master key to encrypt with.
            new_key_id:     Label embedded in the v2 output (default: ``"current"``).

        Returns:
            A list of v2 ciphertexts of the same length, in the same order.

        Raises:
            ValueError: If any ciphertext cannot be decrypted with the current key.
        """
        new_sm = SecretsManager(master_key=new_master_key)
        return [
            new_sm.encrypt_v2(self.decrypt_auto(ct), key_id=new_key_id)
            for ct in ciphertexts
        ]

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def master_key(self) -> str:
        return self._master_key
