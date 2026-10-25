"""JWT authentication (ADR-015). v1 has one configured user (DEMO_USERNAME / DEMO_PASSWORD)."""

from __future__ import annotations

import hmac
from datetime import UTC, datetime, timedelta

import jwt

from docforge.core.config import Settings
from docforge.core.errors import DocForgeError


class AuthError(DocForgeError):
    http_status = 401
    code = "unauthorized"


def authenticate(settings: Settings, username: str, password: str) -> str:
    """Return the username when credentials match; constant-time comparison."""
    user_ok = hmac.compare_digest(username.encode(), settings.demo_username.encode())
    pass_ok = hmac.compare_digest(password.encode(), settings.demo_password.encode())
    if not (user_ok and pass_ok):
        raise AuthError("invalid username or password")
    return settings.demo_username


def create_token(settings: Settings, subject: str, *, now: datetime | None = None) -> tuple[str, int]:
    issued = now or datetime.now(UTC)
    expires_in = settings.jwt_expire_minutes * 60
    payload = {"sub": subject, "iat": issued, "exp": issued + timedelta(seconds=expires_in)}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm), expires_in


def verify_token(settings: Settings, token: str) -> str:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "exp"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError("invalid token") from exc
    return str(payload["sub"])
