from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from docforge.api.deps import current_user, get_container
from docforge.container import Container
from docforge.core.auth import authenticate, create_token

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


@router.post("/auth/login")
def login(body: LoginRequest, c: Container = Depends(get_container)) -> TokenResponse:
    user = authenticate(c.settings, body.username, body.password)
    token, expires_in = create_token(c.settings, user)
    return TokenResponse(access_token=token, expires_in=expires_in)


@router.get("/auth/me")
def me(user: str = Depends(current_user)) -> dict:
    return {"username": user}
