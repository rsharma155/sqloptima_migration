"""Tests for JWT signing-key rotation and RS256 dual-mode (§12.5)."""
from __future__ import annotations

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import jwt

import apps.api.middleware.auth as auth_mod


def _rsa_pem_pair() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_pem, public_pem


def test_decode_accepts_previous_secret(monkeypatch):
    monkeypatch.setattr(auth_mod, "JWT_SECRET", "current-secret-key-32chars-minimum!!")
    monkeypatch.setattr(auth_mod, "JWT_SECRET_PREVIOUS", "previous-secret-key-32chars-min!!!")
    monkeypatch.setattr(auth_mod, "JWT_ALGORITHM", "HS256")
    monkeypatch.setattr(auth_mod, "JWT_PRIVATE_KEY", None)
    monkeypatch.setattr(auth_mod, "JWT_PUBLIC_KEY", None)

    token = auth_mod.create_access_token("user-1", "admin")
    payload = auth_mod._decode(token)
    assert payload["sub"] == "user-1"

    old_token = jwt.encode(
        {"sub": "legacy", "role": "viewer", "typ": "access"},
        "previous-secret-key-32chars-min!!!",
        algorithm="HS256",
    )
    legacy = auth_mod._decode(old_token)
    assert legacy["sub"] == "legacy"


def test_rs256_round_trip(monkeypatch):
    private_pem, public_pem = _rsa_pem_pair()
    monkeypatch.setattr(auth_mod, "JWT_PRIVATE_KEY", private_pem)
    monkeypatch.setattr(auth_mod, "JWT_PUBLIC_KEY", public_pem)
    monkeypatch.setattr(auth_mod, "JWT_PUBLIC_KEY_PREVIOUS", None)
    monkeypatch.setattr(auth_mod, "JWT_ALGORITHM", "RS256")
    monkeypatch.setattr(auth_mod, "JWT_SECRET", "current-secret-key-32chars-minimum!!")

    token = auth_mod.create_access_token("rs-user", "operator")
    header = jwt.get_unverified_header(token)
    assert header["alg"] == "RS256"
    payload = auth_mod._decode(token)
    assert payload["sub"] == "rs-user"
    assert payload["role"] == "operator"


def test_rs256_mode_still_accepts_hs256_legacy(monkeypatch):
    private_pem, public_pem = _rsa_pem_pair()
    monkeypatch.setattr(auth_mod, "JWT_PRIVATE_KEY", private_pem)
    monkeypatch.setattr(auth_mod, "JWT_PUBLIC_KEY", public_pem)
    monkeypatch.setattr(auth_mod, "JWT_ALGORITHM", "RS256")
    monkeypatch.setattr(auth_mod, "JWT_SECRET", "current-secret-key-32chars-minimum!!")
    monkeypatch.setattr(auth_mod, "JWT_SECRET_PREVIOUS", None)

    hs_token = jwt.encode(
        {"sub": "legacy-hs", "role": "viewer", "typ": "access"},
        "current-secret-key-32chars-minimum!!",
        algorithm="HS256",
    )
    payload = auth_mod._decode(hs_token)
    assert payload["sub"] == "legacy-hs"
