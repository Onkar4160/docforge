from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pptx import Presentation

from docforge.api.app import create_app
from docforge.core.auth import AuthError, authenticate, create_token, verify_token
from tests.conftest import make_settings


def _pptx() -> bytes:
    buf = io.BytesIO()
    Presentation().save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------- ops


def test_health_reports_components(client: TestClient):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["database"] is True
    assert body["llm"]["provider"] == "fake"
    assert body["llm"]["primary_model"] == "gemini-3.8-flash"
    assert body["web_search"] == {"provider": "fixture", "authenticated": False}
    assert body["vector_store"] == "local"
    assert body["default_templates"] == {"pptx": False, "docx": False, "xlsx": False}


def test_index_served_without_auth(client: TestClient):
    r = client.get("/")
    assert r.status_code == 200 and "DocForge" in r.text


# ---------------------------------------------------------------- auth (ADR-015)


def test_login_and_me(client: TestClient, settings):
    r = client.post("/api/auth/login", json={"username": "demo", "password": "demo123"})
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer" and body["expires_in"] == settings.jwt_expire_minutes * 60
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.json() == {"username": "demo"}


def test_login_rejects_bad_password(client: TestClient):
    r = client.post("/api/auth/login", json={"username": "demo", "password": "nope"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"


def test_api_requires_token(client: TestClient):
    assert client.post("/api/sessions", json={}).status_code == 401
    r = client.post("/api/sessions", json={}, headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"


def test_token_helpers(settings):
    assert authenticate(settings, "demo", "demo123") == "demo"
    token, _ = create_token(settings, "demo")
    assert verify_token(settings, token) == "demo"
    old, _ = create_token(settings, "demo", now=datetime.now(UTC) - timedelta(days=2))
    with pytest.raises(AuthError, match="expired"):
        verify_token(settings, old)
    other = settings.model_copy(update={"jwt_secret": "another-secret-value-long-enough-123"})
    with pytest.raises(AuthError, match="invalid"):
        verify_token(other, token)


def test_prod_refuses_placeholder_secret(tmp_path):
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        create_app(make_settings(tmp_path, app_env="prod", jwt_secret="change-me-to-a-random-secret"))


def test_auth_can_be_disabled(tmp_path, fake_llm, fixture_search):
    from tests.conftest import _build

    s = make_settings(tmp_path, auth_enabled=False)
    with TestClient(create_app(s, container_factory=lambda st: _build(st, fake_llm, fixture_search))) as c:
        assert c.post("/api/sessions", json={}).status_code == 201


# ---------------------------------------------------------------- sessions


def test_session_upload_message_flow(auth_client: TestClient, fake_llm):  # FR-CONV-1, FR-UX-2
    from docforge.models.intent import Interpretation

    fake_llm.add("interpreter", Interpretation(kind="question", confidence=0.9, objective="q"))
    sid = auth_client.post("/api/sessions", json={"title": "Board deck"}).json()["id"]
    up = auth_client.post(
        f"/api/sessions/{sid}/files",
        files={"file": ("brand.pptx", _pptx(), "application/octet-stream")},
        data={"role": "template"},
    )
    assert up.status_code == 201, up.text
    file_id = up.json()["id"]
    assert up.json()["role"] == "template"

    dl = auth_client.get(f"/api/sessions/{sid}/files/{file_id}")
    assert dl.status_code == 200 and dl.content[:2] == b"PK"

    msg = auth_client.post(
        f"/api/sessions/{sid}/messages", json={"content": "Make a deck", "file_ids": [file_id]}
    )
    assert msg.status_code == 200
    assert msg.json()["reply"]["role"] == "assistant"

    state = auth_client.get(f"/api/sessions/{sid}").json()
    assert state["session"]["owner"] == "demo"
    assert [m["role"] for m in state["messages"]] == ["user", "assistant"]
    assert [f["filename"] for f in state["files"]] == ["brand.pptx"]


def test_foreign_session_looks_missing(auth_client: TestClient, settings):
    sid = auth_client.post("/api/sessions", json={}).json()["id"]
    token, _ = create_token(settings, "mallory")
    r = auth_client.get(f"/api/sessions/{sid}", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 404


def test_unknown_session_is_404(auth_client: TestClient):
    r = auth_client.get("/api/sessions/ses_missing")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


def test_upload_rejects_bad_content(auth_client: TestClient):
    sid = auth_client.post("/api/sessions", json={}).json()["id"]
    r = auth_client.post(
        f"/api/sessions/{sid}/files", files={"file": ("x.pptx", b"not a zip", "application/octet-stream")}
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "unsupported_file"


def test_upload_rejects_non_office_template(auth_client: TestClient):
    sid = auth_client.post("/api/sessions", json={}).json()["id"]
    r = auth_client.post(
        f"/api/sessions/{sid}/files",
        files={"file": ("notes.txt", b"hello", "text/plain")},
        data={"role": "template"},
    )
    assert r.status_code == 400


def test_upload_size_limit(auth_client: TestClient):
    sid = auth_client.post("/api/sessions", json={}).json()["id"]
    big = b"a" * (1024 * 1024 + 10)
    r = auth_client.post(f"/api/sessions/{sid}/files", files={"file": ("big.txt", big, "text/plain")})
    assert r.status_code == 413


def test_message_with_foreign_file_rejected(auth_client: TestClient):
    sid = auth_client.post("/api/sessions", json={}).json()["id"]
    r = auth_client.post(f"/api/sessions/{sid}/messages", json={"content": "hi", "file_ids": ["fil_nope"]})
    assert r.status_code == 400
