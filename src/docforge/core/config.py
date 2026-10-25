"""Application settings from environment variables and ``.env``.

Variable names match the project ``.env`` exactly (no prefix). Nothing here is tied to a single
vendor: the LLM, web search and vector store are selected by configuration (ADR-004, ADR-005, ADR-014).
"""

from __future__ import annotations

import shutil
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_LIBREOFFICE_CANDIDATES = (
    "C:/Program Files/LibreOffice/program/soffice.exe",
    "C:/Program Files (x86)/LibreOffice/program/soffice.exe",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    "/usr/bin/soffice",
    "/usr/lib/libreoffice/program/soffice",
)

DEFAULT_JWT_SECRET = "change-me-to-a-random-secret"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_env: Literal["dev", "test", "prod"] = "dev"
    storage_dir: Path = Path("./storage")

    # ─── API keys ───────────────────────────────────────────
    gemini_api_key: str | None = None
    pinecone_api_key: str | None = None
    pinecone_index: str = "doc-chatbot"
    pinecone_cloud: str = "aws"
    pinecone_region: str = "us-east-1"
    pinecone_api_version: str = "2026-07"
    tavily_api_key: str | None = None
    # Require the authenticated Tavily provider; false allows a keyless development fallback.
    require_authenticated_web_search: bool = True

    # ─── Auth ───────────────────────────────────────────────
    jwt_secret: str = DEFAULT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480
    demo_username: str = "demo"
    demo_password: str = "demo123"
    auth_enabled: bool = True

    # ─── Database ───────────────────────────────────────────
    database_url: str = "sqlite:///./storage/app.db"

    # ─── Upload limits ──────────────────────────────────────
    upload_max_mb: int = 25

    # ─── LLM ────────────────────────────────────────────────
    # Model spec is "model" (uses llm_provider) or "provider:model", e.g. "openai_compat:llama3.1".
    llm_provider: Literal["gemini", "openai_compat", "fake"] = "gemini"
    llm_primary_model: str = "gemini-3.8-flash"
    # Comma-separated; tried in order when a model is retired, out of quota or keeps failing.
    llm_fallback_model: str | None = "gemini-3.7-flash,gemini-3.5-flash,gemini-3.1-flash-lite"
    llm_max_retries: int = 3
    llm_temperature: float = 0.3
    llm_max_output_tokens: int = 8192
    llm_timeout_s: float = 180.0
    # Use the provider's native JSON-schema constraint when it has one; prompt+validate always applies.
    llm_native_schema: bool = False
    llm_repair_attempts: int = 1
    interpreter_timeout_s: float = 45.0
    interpreter_max_retries: int = 1
    interpreter_max_models: int = 2
    llm_agent_model: dict[str, str] = Field(default_factory=dict)
    llm_cassette_mode: Literal["off", "record", "replay"] = "off"
    llm_cassette_dir: Path | None = None
    # Any OpenAI-compatible chat-completions server (OpenAI, Ollama, vLLM, LM Studio, OpenRouter...).
    openai_compat_base_url: str = "http://localhost:11434/v1"
    openai_compat_api_key: str | None = None

    # ─── Embeddings / vector store ──────────────────────────
    embedding_provider: Literal["gemini", "openai_compat", "hash"] = "gemini"
    embedding_model: str = "gemini-embedding-001"
    embedding_dimensions: int = 768
    vector_store: Literal["auto", "pinecone", "local"] = "auto"

    # ─── Research ───────────────────────────────────────────
    # Scholarly sources (all optional keys; keyless use is rate-limited by each provider).
    openalex_api_key: str | None = None
    semantic_scholar_api_key: str | None = None
    research_contact_email: str | None = None
    academic_sources: list[str] = Field(default_factory=lambda: ["openalex", "semantic_scholar", "arxiv"])
    research_enabled: bool = True
    research_max_searches: int = 8
    research_max_results: int = 6
    research_allowed_domains: list[str] = Field(default_factory=list)
    research_blocked_domains: list[str] = Field(default_factory=list)

    # ─── Images ─────────────────────────────────────────────
    images_enabled: bool = True
    image_provider: Literal["auto", "openverse", "pexels", "none"] = "auto"
    pexels_api_key: str | None = None
    max_images_per_deck: int = 6

    # ─── Templates ──────────────────────────────────────────
    default_docx_template_path: Path | None = Path("data/sample_templates/Company_Proposal.docx")
    default_pptx_template_path: Path | None = Path(
        "data/sample_templates/Green Cream Simple Aesthetic Watercolor Presentation.pptx"
    )
    default_xlsx_template_path: Path | None = None
    # Optional external design-guide extractor; command/args are configurable because no
    # single CLI contract is assumed. {input} and {output_dir} are substituted.
    pptx_masters_enabled: bool = False
    pptx_masters_command: str = "pptx-masters"
    pptx_masters_args: str = "{input} --output {output_dir}"
    pptx_masters_timeout_s: float = 120.0

    # ─── Pipeline ───────────────────────────────────────────
    clarify_threshold: float = 0.6
    max_repair_iterations: int = 3
    libreoffice_path: Path | None = None

    log_level: str = "INFO"
    log_json: bool = False

    @field_validator(
        "research_allowed_domains", "research_blocked_domains", "academic_sources", mode="before"
    )
    @classmethod
    def _split_csv(cls, v: object) -> object:
        if isinstance(v, str):
            return [d.strip() for d in v.split(",") if d.strip()]
        return v

    @field_validator(
        "llm_fallback_model",
        "gemini_api_key",
        "pinecone_api_key",
        "tavily_api_key",
        "openai_compat_api_key",
        "openalex_api_key",
        "semantic_scholar_api_key",
        "pexels_api_key",
        "default_docx_template_path",
        "default_pptx_template_path",
        "default_xlsx_template_path",
        mode="before",
    )
    @classmethod
    def _blank_is_none(cls, v: object) -> object:
        # Placeholder values from .env.example count as unset.
        if isinstance(v, str) and (not v.strip() or v.strip().startswith("your-")):
            return None
        return v

    # ----------------------------------------------------------------- derived

    @property
    def blob_dir(self) -> Path:
        return self.storage_dir / "blobs"

    @property
    def resolved_cassette_dir(self) -> Path:
        return self.llm_cassette_dir or self.storage_dir / "cassettes"

    @property
    def max_upload_bytes(self) -> int:
        return self.upload_max_mb * 1024 * 1024

    @property
    def resolved_vector_store(self) -> Literal["pinecone", "local"]:
        if self.vector_store == "auto":
            return "pinecone" if self.pinecone_api_key else "local"
        return self.vector_store

    @property
    def jwt_secret_is_default(self) -> bool:
        return self.jwt_secret == DEFAULT_JWT_SECRET

    @property
    def fallback_models(self) -> list[str]:
        return [m.strip() for m in (self.llm_fallback_model or "").split(",") if m.strip()]

    def model_for(self, agent: str) -> str:
        return self.llm_agent_model.get(agent, self.llm_primary_model)

    def default_template(self, fmt: str) -> Path | None:
        """Configured default template for a format, or None when unset or missing on disk."""
        path = {
            "docx": self.default_docx_template_path,
            "pptx": self.default_pptx_template_path,
            "xlsx": self.default_xlsx_template_path,
        }.get(fmt)
        return path if path is not None and path.is_file() else None

    def find_libreoffice(self) -> Path | None:
        """Locate ``soffice``; None means visual/convert checks are reported as skipped (ADR-009)."""
        if self.libreoffice_path:
            return self.libreoffice_path if self.libreoffice_path.exists() else None
        on_path = shutil.which("soffice") or shutil.which("libreoffice")
        if on_path:
            return Path(on_path)
        for candidate in _LIBREOFFICE_CANDIDATES:
            if Path(candidate).exists():
                return Path(candidate)
        return None

    def ensure_dirs(self) -> None:
        for d in (self.storage_dir, self.blob_dir):
            d.mkdir(parents=True, exist_ok=True)
        prefix = "sqlite:///"
        if self.database_url.startswith(prefix) and ":memory:" not in self.database_url:
            Path(self.database_url[len(prefix) :]).parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
