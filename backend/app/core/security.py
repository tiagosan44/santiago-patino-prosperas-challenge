"""JWT helpers using HS256 (symmetric).

Centralizes create / decode logic so the rest of the app does not
import jose directly. Tokens carry only the subject (username); the
rest of the user record is fetched from DynamoDB on demand.

For production we would add: refresh tokens, token revocation list
(in DynamoDB with TTL), short-lived SSE tokens. Out of scope here.
"""
from datetime import UTC, datetime, timedelta

from jose import jwt

from .config import get_settings


def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
    settings = get_settings()
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.jwt_expiry_minutes)
    expire = datetime.now(UTC) + expires_delta
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """Decodes and verifies the token. Raises jose.JWTError on any failure."""
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
