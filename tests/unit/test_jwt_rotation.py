"""Tests for JWT signing-key rotation (§12.5)."""
from __future__ import annotations

import jwt

import apps.api.middleware.auth as auth_mod


def test_decode_accepts_previous_secret(monkeypatch):
    monkeypatch.setattr(auth_mod, "JWT_SECRET", "current-secret-key-32chars-minimum!!")
    monkeypatch.setattr(auth_mod, "JWT_SECRET_PREVIOUS", "previous-secret-key-32chars-min!!!")

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
