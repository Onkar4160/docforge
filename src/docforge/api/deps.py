from __future__ import annotations

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from docforge.container import Container
from docforge.core.auth import AuthError, verify_token

_bearer = HTTPBearer(auto_error=False)


def get_container(request: Request) -> Container:
    return request.app.state.container


def current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    container = get_container(request)
    if not container.settings.auth_enabled:
        return container.settings.demo_username
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthError("missing bearer token")
    return verify_token(container.settings, credentials.credentials)
