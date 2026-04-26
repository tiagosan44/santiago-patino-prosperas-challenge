"""Unit tests for JWT helpers."""
from datetime import timedelta

import pytest
from jose import JWTError

from app.core import security


def test_create_access_token_includes_subject():
    token = security.create_access_token(subject="user-123")
    payload = security.decode_access_token(token)
    assert payload["sub"] == "user-123"


def test_create_access_token_includes_expiry():
    token = security.create_access_token(subject="u", expires_delta=timedelta(minutes=5))
    payload = security.decode_access_token(token)
    assert "exp" in payload


def test_decode_access_token_rejects_tampered_token():
    token = security.create_access_token(subject="user-123")
    tampered = token[:-4] + "AAAA"  # corrupt last 4 chars of signature
    with pytest.raises(JWTError):
        security.decode_access_token(tampered)


def test_decode_access_token_rejects_expired_token():
    token = security.create_access_token(
        subject="u", expires_delta=timedelta(seconds=-10)  # already expired
    )
    with pytest.raises(JWTError):
        security.decode_access_token(token)
