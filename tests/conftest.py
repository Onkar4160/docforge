from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from docforge.api.app import create_app
from docforge.container import Container
from docforge.core.config import Settings
from docforge.llm import FakeLLMClient
from docforge.llm.providers import HashingEmbeddingProvider
from docforge.research.search import FixtureSearchProvider


def make_settings(tmp_path: Path, **overrides) -> Settings:
    """Settings isolated from the developer's .env and environment keys."""
    base = dict(
        _env_file=None,
        app_env="test",
        storage_dir=tmp_path / "storage",
        database_url=f"sqlite:///{(tmp_path / 'storage' / 'app.db').as_posix()}",
        llm_provider="fake",
        llm_primary_model="gemini-3.8-flash",
        llm_fallback_model="gemini-3.7-flash",
        gemini_api_key=None,
        tavily_api_key=None,
        pinecone_api_key=None,
        embedding_provider="hash",
        images_enabled=False,
        research_enabled=False,
        upload_max_mb=1,
        jwt_secret="test-secret-with-enough-length-for-hs256",
        default_docx_template_path=None,
        default_pptx_template_path=None,
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def fake_llm() -> FakeLLMClient:
    return FakeLLMClient()


@pytest.fixture
def fixture_search() -> FixtureSearchProvider:
    return FixtureSearchProvider({})


def _build(settings: Settings, fake_llm: FakeLLMClient, search: FixtureSearchProvider) -> Container:
    return Container.build(
        settings, llm=fake_llm, search=search, academic=[], embedder=HashingEmbeddingProvider(64)
    )


@pytest.fixture
def container(settings, fake_llm, fixture_search) -> Iterator[Container]:
    c = _build(settings, fake_llm, fixture_search)
    yield c
    c.engine.dispose()


@pytest.fixture
def client(settings, fake_llm, fixture_search) -> Iterator[TestClient]:
    app = create_app(settings, container_factory=lambda s: _build(s, fake_llm, fixture_search))
    with TestClient(app) as tc:
        yield tc


@pytest.fixture
def auth_client(client: TestClient, settings: Settings) -> TestClient:
    token = client.post(
        "/api/auth/login", json={"username": settings.demo_username, "password": settings.demo_password}
    ).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
